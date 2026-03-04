#!/usr/bin/env python3
# Serveur SSH avec select() au lieu de threading
# Nécessite : pip install paramiko

import socket
import sys
import argparse
import select
import subprocess
import os
import paramiko

# ── Configuration ────────────────────────────────────────────────────
host          = '10.10.50.52'  # identique à l'original
data_payload  = 2048
backlog       = 5
HOST_KEY_FILE = "server_rsa_key"
USERNAME      = "admin"
PASSWORD      = "password123"


# ── Clé RSA du serveur ───────────────────────────────────────────────
def load_or_generate_host_key(filename):
    if os.path.exists(filename):
        print("[*] Chargement de la clé RSA : %s" % filename)
        return paramiko.RSAKey(filename=filename)
    else:
        print("[*] Génération d'une nouvelle clé RSA -> %s" % filename)
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(filename)
        return key


# ── Interface SSH Paramiko ───────────────────────────────────────────
class SSHServerInterface(paramiko.ServerInterface):
    def __init__(self):
        self.shell_requested  = False
        self.exec_command     = None

    def check_auth_password(self, username, password):
        if username == USERNAME and password == PASSWORD:
            print("[+] Authentification réussie : %s" % username)
            return paramiko.AUTH_SUCCESSFUL
        print("[-] Échec authentification : %s" % username)
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return 'password'

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height,
                                   pixelwidth, pixelheight, modes):
        return True

    def check_channel_shell_request(self, channel):
        self.shell_requested = True
        return True

    def check_channel_exec_request(self, channel, command):
        self.exec_command = command.decode('utf-8', errors='replace')
        return True


# ── État d'un client connecté ────────────────────────────────────────
class ClientSession:
    """
    Regroupe tous les objets liés à une session SSH active :
      - transport Paramiko
      - canal SSH
      - process cmd.exe (si shell interactif)
    """
    def __init__(self, transport, channel, process=None, exec_mode=False):
        self.transport   = transport
        self.channel     = channel
        self.process     = process      # subprocess.Popen (shell interactif)
        self.exec_mode   = exec_mode    # True → commande unique, pas de boucle I/O


# ── Négociation SSH (synchrone, appelée une seule fois par client) ───
def negotiate_ssh(client_socket, client_address, host_key):
    """
    Effectue le handshake SSH complet et retourne un ClientSession,
    ou None si la négociation échoue.
    """
    print("[+] Connexion : %s:%s" % client_address)

    transport = paramiko.Transport(client_socket)
    transport.add_server_key(host_key)
    iface = SSHServerInterface()

    try:
        transport.start_server(server=iface)
    except paramiko.SSHException as e:
        print("[-] Négociation SSH échouée : %s" % e)
        return None

    # Attente du canal (30 s)
    channel = transport.accept(30)
    if channel is None:
        print("[-] Aucun canal ouvert")
        transport.close()
        return None

    # Attente de la requête shell/exec (5 s, poll manuel)
    for _ in range(50):
        if iface.shell_requested or iface.exec_command:
            break
        import time; time.sleep(0.1)

    # ── Commande unique ──────────────────────────────────────────────
    if iface.exec_command:
        print("[*] Exec : %s" % iface.exec_command)
        result = subprocess.run(
            iface.exec_command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        channel.sendall(result.stdout)
        if result.stderr:
            channel.sendall_stderr(result.stderr)
        channel.send_exit_status(result.returncode)
        channel.close()
        transport.close()
        return None   # session terminée immédiatement

    # ── Shell interactif ─────────────────────────────────────────────
    if iface.shell_requested:
        print("[*] Shell interactif ouvert pour %s:%s" % client_address)
        process = subprocess.Popen(
            'cmd.exe',
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return ClientSession(transport, channel, process=process)

    print("[-] Ni shell ni exec reçu")
    transport.close()
    return None


# ── Boucle principale avec select() ─────────────────────────────────
def echo_server(port):
    """ A simple SSH server using select() instead of threading """
    host_key = load_or_generate_host_key(HOST_KEY_FILE)

    # Create a TCP socket  ← identique à l'original
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Enable reuse address/port  ← identique
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Bind the socket to the port  ← identique
    server_address = (host, port)
    print("Starting up SSH server on %s port %s" % server_address)
    sock.bind(server_address)
    # Listen to clients  ← identique
    sock.listen(backlog)
    sock.setblocking(False)   # non-bloquant pour select()

    print("Login : %s  /  Mot de passe : %s" % (USERNAME, PASSWORD))
    print("Connexion : ssh %s@localhost -p %s" % (USERNAME, port))

    # ── Registres select() ───────────────────────────────────────────
    # sessions  : dict  fd_stdout_process → ClientSession
    # channels  : dict  canal_fileno      → ClientSession
    sessions = {}   # stdout du process  → session
    channels = {}   # channel fileno     → session

    while True:
        print("Waiting to receive message from client")

        # Construire la liste des fd à surveiller
        read_fds = [sock]

        for session in list(sessions.values()):
            # stdout/stderr du cmd.exe
            if session.process and session.process.stdout:
                read_fds.append(session.process.stdout)
            if session.process and session.process.stderr:
                read_fds.append(session.process.stderr)
            # canal SSH entrant (frappe clavier du client)
            try:
                read_fds.append(session.channel)
            except Exception:
                pass

        # select() bloque jusqu'à qu'un fd soit prêt (timeout 1 s)
        try:
            readable, _, exceptional = select.select(read_fds, [], read_fds, 1.0)
        except (ValueError, OSError):
            # Un fd invalide (session fermée) → nettoyage
            _cleanup_closed(sessions, channels)
            continue

        for fd in readable:

            # ── Nouvelle connexion TCP ───────────────────────────────
            if fd is sock:
                client_socket, client_address = sock.accept()
                session = negotiate_ssh(client_socket, client_address, host_key)
                if session:
                    # Enregistrer la session indexée par stdout du process
                    sessions[session.process.stdout.fileno()] = session
                    channels[session.channel.fileno()]         = session
                continue

            # ── Données stdout du cmd.exe → envoyer au client SSH ────
            stdout_fd = fd.fileno() if hasattr(fd, 'fileno') else None
            if stdout_fd in sessions:
                session = sessions[stdout_fd]
                try:
                    data = os.read(stdout_fd, data_payload)
                    if data:
                        session.channel.send(data)
                    else:
                        _close_session(session, sessions, channels)
                except OSError:
                    _close_session(session, sessions, channels)
                continue

            # ── Données stderr du cmd.exe → envoyer au client SSH ────
            if hasattr(fd, 'fileno'):
                for session in list(sessions.values()):
                    if (session.process and
                            session.process.stderr and
                            fd.fileno() == session.process.stderr.fileno()):
                        try:
                            data = os.read(fd.fileno(), data_payload)
                            if data:
                                session.channel.send_stderr(data)
                        except OSError:
                            pass
                        break
                continue

            # ── Données du client SSH → stdin du cmd.exe ─────────────
            if hasattr(fd, 'fileno') and fd.fileno() in channels:
                session = channels[fd.fileno()]
                try:
                    data = session.channel.recv(data_payload)
                    if data:
                        session.process.stdin.write(data)
                        session.process.stdin.flush()
                    else:
                        _close_session(session, sessions, channels)
                except Exception:
                    _close_session(session, sessions, channels)
                continue

        # ── Nettoyage des sessions avec canal/process fermé ──────────
        for session in list(sessions.values()):
            if session.channel.closed or not session.transport.is_active():
                _close_session(session, sessions, channels)


# ── Fermeture propre d'une session ───────────────────────────────────
def _close_session(session, sessions, channels):
    """Ferme le process, le canal et le transport d'une session."""
    try:
        stdout_fd = session.process.stdout.fileno()
        sessions.pop(stdout_fd, None)
    except Exception:
        pass
    try:
        channels.pop(session.channel.fileno(), None)
    except Exception:
        pass
    try:
        session.process.terminate()
    except Exception:
        pass
    try:
        session.channel.close()
    except Exception:
        pass
    try:
        session.transport.close()
    except Exception:
        pass
    print("[*] Session fermée")


# ── Nettoyage des fd invalides ────────────────────────────────────────
def _cleanup_closed(sessions, channels):
    for session in list(sessions.values()):
        if session.channel.closed or not session.transport.is_active():
            _close_session(session, sessions, channels)


# ── Point d'entrée (identique à l'original) ──────────────────────────
if __name__ == '__main__':
    try:
        import paramiko
    except ImportError:
        print("[!] Paramiko manquant. Executez : pip install paramiko")
        sys.exit(1)

    parser = argparse.ArgumentParser(description='SSH Server Example with select()')
    parser.add_argument('--port', action="store", dest="port", type=int, required=True)
    given_args = parser.parse_args()
    port = given_args.port

    echo_server(port)