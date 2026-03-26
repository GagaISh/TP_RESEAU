import socket
import select
import subprocess
import paramiko
import threading
import os

# -- Configuration --
HOST = '0.0.0.0'  # Écoute sur toutes les interfaces
PORT = 2222
USERNAME = "admin"
PASSWORD = "password123"
KEY_FILE = "server_rsa_key"

# --- 1. Le Pont (Bridge) pour Windows ---
def bridge_worker(pipe, sock_writer):
    """Lit la sortie de cmd.exe et l'envoie dans le socket bridge"""
    try:
        while True:
            data = pipe.read(1) # Caractère par caractère
            if not data: break
            sock_writer.sendall(data)
    except: pass

def create_socket_bridge():
    """Crée une paire de sockets locaux pour tromper select()"""
    serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serv.bind(('127.0.0.1', 0))
    serv.listen(1)
    writer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    writer.connect(serv.getsockname())
    reader, _ = serv.accept()
    serv.close()
    return reader, writer

# --- 2. Interface SSH ---
class SSHServer(paramiko.ServerInterface):
    def check_auth_password(self, u, p):
        if u == USERNAME and p == PASSWORD: return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED
    def check_channel_request(self, kind, chanid): return paramiko.OPEN_SUCCEEDED
    def check_channel_shell_request(self, chan): return True
    def check_channel_pty_request(self, *args): return True

# --- 3. Initialisation de la clé ---
if not os.path.exists(KEY_FILE):
    paramiko.RSAKey.generate(2048).write_private_key_file(KEY_FILE)
host_key = paramiko.RSAKey(filename=KEY_FILE)

# --- 4. Lancement du serveur ---
server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_sock.bind((HOST, PORT))
server_sock.listen(5)
server_sock.setblocking(False)

sessions = {} # bridge_fd -> session_data
channels = {} # chan_fd -> session_data

print(f"[*] Serveur SSH actif sur le port {PORT}...")

while True:
    # On surveille le socket serveur + tous les sockets clients + tous les bridges
    read_fds = [server_sock]
    for s in sessions.values():
        read_fds.append(s['bridge'])
        read_fds.append(s['chan'])

    try:
        r, _, _ = select.select(read_fds, [], [], 0.1)
    except: continue

    for fd in r:
        # A. NOUVELLE CONNEXION
        if fd is server_sock:
            c_sock, addr = server_sock.accept()
            print(f"[+] Client connecté : {addr}")
            
            # Mode bloquant temporaire pour la négociation SSH (évite le Timeout)
            c_sock.setblocking(True) 
            
            t = paramiko.Transport(c_sock)
            t.add_server_key(host_key)
            t.start_server(server=SSHServer())
            
            # 3. On attend l'ouverture du canal (shell)
        chan = t.accept(20)
        if chan:
                    # --- LE CODE MODIFIÉ EST ICI ---
            proc = subprocess.Popen(
                'cmd.exe', 
                stdin=subprocess.PIPE, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
                    
            # Création du pont pour select()
            reader, writer = create_socket_bridge()
            # On utilise bien 'proc.stdout' qui correspond à notre Popen
            threading.Thread(target=bridge_worker, args=(proc.stdout, writer), daemon=True).start()
            # -------------------------------
                    
            # 4. On repasse en NON-BLOQUANT pour le multiplexage select()
            reader.setblocking(False)
            chan.setblocking(False)
                    
            session_data = {'bridge': reader, 'chan': chan, 'proc': proc, 'trans': t}
            sessions[reader.fileno()] = session_data
            channels[chan.fileno()] = session_data
            print(f"[OK] Session SSH établie pour {addr}")
        
        # B. DONNÉES CMD.EXE -> SSH (via le pont)
        elif fd.fileno() in sessions:
            s = sessions[fd.fileno()]
            try:
                data = fd.recv(1024)
                if data: s['chan'].sendall(data)
            except: pass
            
        # C. DONNÉES SSH -> CMD.EXE
        elif fd.fileno() in channels:
            s = channels[fd.fileno()]
            try:
                data = s['chan'].recv(1024)
                if data:
                    s['proc'].stdin.write(data)
                    s['proc'].stdin.flush()
            except: pass