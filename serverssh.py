# server.py
import socket
import select

# ---------------------------
# 1. Créer le socket TCP
# ---------------------------
server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# Permet de réutiliser le port immédiatement après arrêt du serveur
server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# Lier le socket à toutes les interfaces réseau sur le port 2222
server_sock.bind(("0.0.0.0", 2222))

# Mettre en écoute (max 10 connexions en attente)
server_sock.listen(10)

# Mode non-bloquant (obligatoire pour epoll)
server_sock.setblocking(False)

print(" Serveur démarré sur le port 2222")

# ---------------------------
# 2. Créer l'objet epoll
# ---------------------------
epoll = select.epoll()

# Enregistrer le socket serveur pour surveiller les nouvelles connexions
epoll.register(server_sock.fileno(), select.EPOLLIN)

# Dictionnaire pour retrouver une connexion à partir de son fd (file descriptor)
connections = {}

# ---------------------------
# 3. Boucle principale
# ---------------------------
print(" Serveur démarré et en attente de connexions...")

try:
    while True:
        # Attendre qu'un événement arrive (timeout de 1 seconde)
        events = epoll.poll(1)

        for fd, event in events:

            # Cas 1 : nouvelle connexion entrante
            if fd == server_sock.fileno():
                conn, addr = server_sock.accept()
                conn.setblocking(False)

                # Surveiller cette nouvelle connexion
                epoll.register(conn.fileno(), select.EPOLLIN)
                connections[conn.fileno()] = conn

                print(f" Nouveau client connecté : {addr}")

            # Cas 2 : un client existant envoie des données
            elif event & select.EPOLLIN:
                data = connections[fd].recv(1024)

                if data:
                    print(f" Données reçues : {data}")
                else:
                    # Le client s'est déconnecté
                    epoll.unregister(fd)
                    connections[fd].close()
                    del connections[fd]
                    print(f" Client déconnecté")

            # Cas 3 : connexion fermée brutalement
            elif event & select.EPOLLHUP:
                epoll.unregister(fd)
                connections[fd].close()
                del connections[fd]
                print(f" Connexion perdue")

except KeyboardInterrupt:
    print("\n Arrêt du serveur")

finally:
    # Nettoyage propre
    epoll.unregister(server_sock.fileno())
    epoll.close()
    server_sock.close()