"""
Serveur SSH Multiplexé en Python (Implémentation avec Paramiko et Select)

Ce module implémente un serveur SSH capable de gérer plusieurs connexions 
simultanées via le multiplexage d'entrées/sorties (select). 

Particularité technique : La fonction select() sous Windows ne supporte pas 
les descripteurs de fichiers de type "pipe" (utilisés par subprocess). 
Pour contourner cette limitation matérielle/système, ce code implémente un 
"Socket Bridge" (pont réseau local) qui convertit le flux du processus système 
(cmd.exe) en flux socket lisible par select().
"""

import socket
import select
import subprocess
import paramiko
import threading
import os

# -- Configuration --
# Constantes de configuration réseau et d'authentification du serveur
HOST = '10.99.166.170'  # Écoute sur toutes les interfaces
PORT = 2222
USERNAME = "admin"
PASSWORD = "password123"
KEY_FILE = "server_rsa_key"

# --- 1. Le Pont (Bridge) pour Windows ---
def bridge_worker(pipe, sock_writer):
    """
    Thread de travail qui lit la sortie standard du processus système (cmd.exe)
    et l'injecte dans un socket local.
    
    Args:
        pipe: Le flux de lecture (stdout) connecté au processus enfant.
        sock_writer: Le socket local configuré pour envoyer les données.
        
    Pourquoi ? Permet de lire le pipe de manière bloquante dans un thread isolé, 
    puis de transférer les données vers un socket non-bloquant que le thread 
    principal peut surveiller avec select().
    """
    try:
        while True:
            data = pipe.read(1) # Caractère par caractère pour plus de réactivité
            if not data: break
            sock_writer.sendall(data)
    except: pass

def create_socket_bridge():
    """
    Crée une paire de sockets locaux (serveur/client éphémères) connectés entre eux.
    
    Returns:
        tuple: (reader, writer) correspondant aux deux extrémités du canal de communication.
        
    Pourquoi ? C'est le cœur du contournement pour Windows. En connectant un socket 
    sur localhost, on obtient des descripteurs de fichiers réseaux valides que 
    la fonction native select() de Windows accepte de surveiller.
    """
    serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serv.bind(('127.0.0.1', 0)) # Port 0 : demande au système un port libre aléatoire
    serv.listen(1)
    writer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    writer.connect(serv.getsockname())
    reader, _ = serv.accept()
    serv.close() # On ferme le serveur d'écoute, la connexion point-à-point est établie
    return reader, writer

# --- 2. Interface SSH ---
class SSHServer(paramiko.ServerInterface):
    """
    Interface de contrôle Paramiko définissant les règles de sécurité et 
    les permissions du serveur SSH. Surcharge les méthodes par défaut.
    """
    def check_auth_password(self, u, p):
        """Vérifie les identifiants fournis par le client."""
        if u == USERNAME and p == PASSWORD: return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED
        
    def check_channel_request(self, kind, chanid): 
        """Accepte l'ouverture de nouveaux canaux de communication."""
        return paramiko.OPEN_SUCCEEDED
        
    def check_channel_shell_request(self, chan): 
        """Autorise le client à demander l'ouverture d'un interpréteur de commandes."""
        return True
        
    def check_channel_pty_request(self, *args): 
        """Autorise l'allocation d'un pseudo-terminal (PTY) pour l'interactivité."""
        return True

# --- 3. Initialisation de la clé ---
# Génération automatique d'une clé RSA de 2048 bits si elle n'existe pas encore.
# Indispensable pour sécuriser le canal SSH via cryptographie asymétrique.
if not os.path.exists(KEY_FILE):
    paramiko.RSAKey.generate(2048).write_private_key_file(KEY_FILE)
host_key = paramiko.RSAKey(filename=KEY_FILE)

# --- 4. Lancement du serveur ---
server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# SO_REUSEADDR permet de redémarrer le serveur immédiatement sans attendre le timeout TIME_WAIT du système
server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_sock.bind((HOST, PORT))
server_sock.listen(5)
# Mode non-bloquant indispensable pour que select() orchestre le multiplexage sans figer le programme
server_sock.setblocking(False)

# Dictionnaires de suivi des sessions actives pour router correctement les flux I/O
sessions = {} # Fait le lien entre le socket bridge (cmd) et les données de session
channels = {} # Fait le lien entre le socket du canal SSH et les données de session

print(f"[*] Serveur SSH actif sur le port {PORT}...")

# --- 5. Boucle Principale de Multiplexage (Event Loop) ---
while True:
    # On surveille le socket serveur + tous les sockets clients + tous les bridges
    read_fds = [server_sock]
    for s in sessions.values():
        read_fds.append(s['bridge'])
        read_fds.append(s['chan'])

    try:
        # select() bloque pendant 0.1s max en attendant une activité sur l'un des sockets
        r, _, _ = select.select(read_fds, [], [], 0.1)
    except: continue

    for fd in r:
        # A. NOUVELLE CONNEXION
        if fd is server_sock:
            # Étape 1: Accepter la connexion TCP du client SSH
            c_sock, addr = server_sock.accept()
            print(f"[+] Client connecté : {addr}")
            
            # Étape 2: Passage en mode bloquant pour la négociation SSH
            # (évite les timeouts lors de l'authentification cryptographique)
            c_sock.setblocking(True) 
            
            # Étape 3: Initialiser le transport Paramiko et démarrer la négociation SSH
            t = paramiko.Transport(c_sock)
            t.add_server_key(host_key)
            t.start_server(server=SSHServer())
            
            # Étape 4: On attend l'ouverture du canal shell (timeout 20s)
            chan = t.accept(20)
            if chan:
                # --- ÉTAPES DE CRÉATION DE LA SESSION ---
                
                # Étape 5: Lancer le processus cmd.exe local (sans ouvrir de fenêtre visible)
                proc = subprocess.Popen(
                    'cmd.exe', 
                    stdin=subprocess.PIPE, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, # Redirige les erreurs standards vers la sortie standard
                    bufsize=0,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                # Étape 6: Créer une paire de sockets locaux (bridge)
                # car select() ne fonctionne pas directement avec les pipes Windows
                reader, writer = create_socket_bridge()
                
                # Étape 7: Lancer un thread daemon qui lit la sortie de cmd.exe
                # et la transfère dans le socket bridge (pour que select() le détecte)
                threading.Thread(target=bridge_worker, args=(proc.stdout, writer), daemon=True).start()
                
                # Étape 8: Passer les sockets en mode NON-BLOQUANT pour le multiplexage select()
                reader.setblocking(False)
                chan.setblocking(False)
                
                # Étape 9: Enregistrer la session dans les dictionnaires pour le suivi
                session_data = {'bridge': reader, 'chan': chan, 'proc': proc, 'trans': t}
                sessions[reader.fileno()] = session_data
                channels[chan.fileno()] = session_data
                print(f"[OK] Session SSH établie pour {addr}")
        
        # B. DONNÉES CMD.EXE -> SSH (via le pont)
        # Étape 10: Lorsque des données arrivent du pont (sortie cmd.exe),
        # les envoyer au canal SSH vers le client
        elif fd.fileno() in sessions:
            s = sessions[fd.fileno()]
            try:
                data = fd.recv(1024)
                if data: s['chan'].sendall(data)
            except: pass
            
        # C. DONNÉES SSH -> CMD.EXE
        # Étape 11: Lorsque des données arrivent du canal SSH (client),
        # les envoyer à l'entrée standard de cmd.exe
        elif fd.fileno() in channels:
            s = channels[fd.fileno()]
            try:
                data = s['chan'].recv(1024)
                if data:
                    s['proc'].stdin.write(data)
                    s['proc'].stdin.flush() # Force l'envoi immédiat au processus système
            except: pass