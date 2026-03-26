import socket
import sys
import argparse
import paramiko
import threading

# ── Configuration ──
host     = '172.20.10.6'
USERNAME = "admin"
PASSWORD = "password123"

def receiver(channel):
    """Boucle de réception : lit le serveur et affiche à l'écran"""
    try:
        while not channel.exit_status_ready():
            if channel.recv_ready():
                data = channel.recv(2048)
                if data:
                    sys.stdout.write(data.decode('utf-8', errors='replace'))
                    sys.stdout.flush()
            if channel.recv_stderr_ready():
                data = channel.recv_stderr(2048)
                if data:
                    sys.stderr.write(data.decode('utf-8', errors='replace'))
                    sys.stderr.flush()
    except Exception:
        pass

def echo_client(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_address = (host, port)
    print("Connecting to %s port %s" % server_address)
    
    try:
        sock.connect(server_address)
        transport = paramiko.Transport(sock)
        transport.connect(username=USERNAME, password=PASSWORD)

        channel = transport.open_session()
        channel.get_pty()
        channel.invoke_shell()

        print("Connexion SSH établie. Tapez 'exit' pour quitter.\n")

        # Lancement du thread de réception (S'occupe de l'affichage)
        thr = threading.Thread(target=receiver, args=(channel,), daemon=True)
        thr.start()

        # Boucle principale (S'occupe du clavier)
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            channel.sendall(line)
            if line.strip() == 'exit':
                break

    except Exception as e:
        print(f"Erreur : {e}")
    finally:
        print("Closing connection...")
        sock.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SSH Client')
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    echo_client(args.port)