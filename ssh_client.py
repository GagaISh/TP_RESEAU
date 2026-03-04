#!/usr/bin/env python3
# Client SSH basé sur le client echo TCP original
# Nécessite : pip install paramiko

import socket
import sys
import argparse
import paramiko

# ── Configuration (remplace les variables globales du client echo) ───
host     = '10.57.252.57'   # identique à l'original
USERNAME = "admin"
PASSWORD = "password123"


# ── Fonction principale (structure identique à echo_client) ──────────
def echo_client(port):
    """ A simple SSH client (was: echo client) """

    # Create a TCP/IP socket  ← identique à l'original
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Connect the socket to the server  ← identique
    server_address = (host, port)
    print("Connecting to %s port %s" % server_address)
    sock.connect(server_address)

    try:
        # ── Négociation SSH (remplace sendall/recv) ──────────────────
        transport = paramiko.Transport(sock)
        transport.connect(username=USERNAME, password=PASSWORD)

        # Ouvrir une session SSH (équivalent du canal de communication)
        channel = transport.open_session()
        channel.get_pty()           # demander un pseudo-terminal
        channel.invoke_shell()      # démarrer le shell interactif

        print("Connexion SSH établie. Tapez vos commandes (exit pour quitter)\n")

        # ── Boucle interactive (remplace la boucle recv) ─────────────
        import select, sys

        while True:
            # Surveiller : sortie du serveur  ET  saisie clavier locale
            readable, _, _ = select.select([channel, sys.stdin], [], [], 0.5)

            for fd in readable:

                # Données reçues du serveur SSH → afficher
                if fd is channel:
                    if channel.exit_status_ready():
                        print("\n[*] Le serveur a fermé la session")
                        channel.close()
                        transport.close()
                        return
                    data = channel.recv(1024)
                    if data:
                        # Avant : print("Received: %s" % data)
                        sys.stdout.write(data.decode('utf-8', errors='replace'))
                        sys.stdout.flush()

                # Frappe clavier locale → envoyer au serveur SSH
                if fd is sys.stdin:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    # Avant : sock.sendall(message.encode('utf-8'))
                    channel.send(line)

    except paramiko.AuthenticationException:
        print("Erreur : authentification refusée (%s)" % USERNAME)
    except paramiko.SSHException as e:
        print("Erreur SSH : %s" % str(e))
    except socket.error as e:
        print("Socket error: %s" % str(e))     # ← même message qu'à l'original
    except Exception as e:
        print("Other exception: %s" % str(e))  # ← même message qu'à l'original
    finally:
        print("Closing connection to the server")  # ← même message qu'à l'original
        sock.close()


# ── Point d'entrée (identique à l'original) ─────────────────────────
if __name__ == '__main__':
    try:
        import paramiko
    except ImportError:
        print("[!] Paramiko manquant. Executez : pip install paramiko")
        sys.exit(1)

    parser = argparse.ArgumentParser(description='SSH Client Example')  # était: Socket Server Example
    parser.add_argument('--port', action="store", dest="port", type=int, required=True)
    given_args = parser.parse_args()
    port = given_args.port

    echo_client(port)
