"""
Client SSH Interactif en Python (Implémentation avec Paramiko)

Ce module implémente la partie cliente du projet de serveur SSH. 
Il établit une connexion TCP, négocie le protocole SSH via Paramiko, 
et gère l'interactivité utilisateur.

Choix architectural majeur : La gestion asynchrone des Entrées/Sorties.
Sous Windows, la fonction select() ne peut pas surveiller l'entrée standard (sys.stdin).
Pour éviter qu'une attente de frappe clavier ne bloque la réception des messages 
du serveur, le client est divisé en deux threads d'exécution simultanés :
1. Le thread principal (bloqué sur sys.stdin.readline) qui envoie les commandes.
2. Un thread secondaire (daemon) dédié exclusivement à la réception et à l'affichage.
"""

import socket
import sys
import argparse
import paramiko
import threading

# -- Configuration --
# Utilise '127.0.0.1' si le serveur est sur le même PC, sinon l'IP du serveur
# Note : Ici l'IP réseau est codée en dur pour faciliter les tests avec le binôme
host     = '10.99.166.159' 
USERNAME = "admin"
PASSWORD = "password123"

def receiver(channel):
    """
    Fonction exécutée dans un thread séparé pour écouter en continu 
    les réponses du serveur SSH sans bloquer la saisie utilisateur.
    
    Args:
        channel (paramiko.Channel): Le canal de communication SSH actif.
        
    Pourquoi ? Cette boucle tourne en tâche de fond. Dès que le serveur envoie 
    le résultat d'une commande (comme 'dir' ou 'ipconfig'), ce thread l'attrape 
    et l'imprime immédiatement à l'écran, même si l'utilisateur est en train de taper autre chose.
    """
    try:
        # On continue de lire tant que le serveur n'a pas fermé la connexion
        while not channel.exit_status_ready():
            if channel.recv_ready():
                # On lit jusqu'à 2048 octets à la fois
                data = channel.recv(2048)
                if data:
                    # Décodage en UTF-8 avec errors='replace' pour éviter les crashs 
                    # si Windows renvoie des caractères spéciaux (accents dans cmd)
                    sys.stdout.write(data.decode('utf-8', errors='replace'))
                    sys.stdout.flush() # Force l'affichage immédiat dans la console
    except Exception:
        pass

def echo_client(port):
    """
    Gère le cycle de vie complet de la connexion client : 
    Établissement du socket TCP, authentification SSH, et boucle d'interaction.
    
    Args:
        port (int): Le port sur lequel le serveur SSH écoute.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        print(f"Connecting to {host} port {port}...")
        sock.connect((host, port)) # Étape 1 : Connexion réseau TCP classique
        
        # Initialisation Transport SSH
        # Étape 2 : Superposition de la couche cryptographique Paramiko
        transport = paramiko.Transport(sock)
        transport.connect(username=USERNAME, password=PASSWORD)

        # Étape 3 : Ouverture d'un canal sécurisé multiplexé
        channel = transport.open_session()
        
        # Demande un terminal interactif (Pseudo-Terminal)
        # Pourquoi ? Indispensable pour que le serveur (cmd.exe) traite cette session
        # comme un vrai terminal, gère les retours à la ligne correctement et 
        # affiche le prompt (C:\Users\...)
        channel.get_pty() 
        channel.invoke_shell() # Lance le shell par défaut du système distant

        print("Connexion SSH établie. Tapez vos commandes ci-dessous :\n")

        # Un seul thread pour l'affichage (évite les conflits select sur Windows)
        # L'argument daemon=True assure que ce thread se fermera tout seul 
        # quand le thread principal (le programme) s'arrêtera.
        thr = threading.Thread(target=receiver, args=(channel,), daemon=True)
        thr.start()

        # Boucle principale pour la saisie clavier (Thread principal)
        while True:
            # readline() est bloquant : le programme s'arrête ici jusqu'à ce que 
            # l'utilisateur appuie sur 'Entrée'
            line = sys.stdin.readline()
            if not line:
                break
            
            # Envoi de la commande tapée vers le serveur SSH
            channel.sendall(line)
            
            # Condition de sortie propre
            if line.strip() == 'exit':
                break

    except Exception as e:
        print(f"Erreur : {e}")
    finally:
        # Assure la fermeture propre des ressources réseau en cas d'erreur ou de déconnexion
        sock.close()

# Point d'entrée du script
if __name__ == '__main__':
    # Utilisation d'argparse pour rendre le port paramétrable via le terminal
    # Exemple d'utilisation : python client.py --port 2222
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    echo_client(args.port)