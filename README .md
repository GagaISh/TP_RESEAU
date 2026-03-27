# Serveur et Client SSH Multiplexé en Python

**Projet académique :** Université Paris-Est Créteil (UPEC) - Master 1 Informatique, Parcours Logiciels Sûrs.

Ce projet implémente une architecture Client/Serveur SSH  développée entièrement en Python à l'aide de la bibliothèque `paramiko`. Il démontre la gestion de connexions sécurisées, l'exécution de commandes à distance via un pseudo-terminal (PTY) et le multiplexage des entrées/sorties.

## Objectifs et Défis techniques

L'objectif principal était de concevoir un serveur SSH capable de gérer le multiplexage I/O de manière non-bloquante. 
Des défis architecturaux majeurs ont été surmontés, notamment :
* **Limitation Windows & Multiplexage :** La fonction `select()` sous Windows ne supportant pas les descripteurs de fichiers de type *pipe* (utilisés par `subprocess`), nous avons implémenté un "Socket Bridge" (pont réseau local) pour convertir les flux du processus système (`cmd.exe`) en flux lisibles par `select()`.
* **Contraintes matérielles :** Résolution d'incompatibilités et de contraintes liées à l'architecture ARM lors des phases de développement et de test.
* **Asynchronisme Client :** Utilisation du multithreading côté client pour séparer la saisie utilisateur (bloquante) de la réception continue des données du serveur.

## Prérequis et Installation

Installation de Python 3.x sur votre machine.

1. Clonez ce dépôt Git sur votre machine locale et placez-vous dans le répertoire du projet.
2. Installez les dépendances requises à l'aide du fichier `requirements.txt` :

   pip install -r requirements.txt

## Utilisation

Le projet se compose de deux scripts principaux : le serveur (server.py) et le client (client.py).

1. Lancer le Serveur SSH
Ouvrez un terminal et exécutez le script du serveur. Par défaut, il écoute sur toutes les interfaces (0.0.0.0) sur le port 2222.

    python server.py

Note : Lors du premier lancement, le serveur génère automatiquement sa paire de clés RSA (server_rsa_key).

2. Connecter le Client
Ouvrez un second terminal. Le client prend en paramètre le port de connexion. (L'adresse IP cible est configurable directement dans l'en-tête de client.py).

    python client.py --port 2222

3. Identifiants par défaut
Pour les besoins du test, les identifiants codés en dur dans les scripts sont :

    Utilisateur : admin
    Mot de passe : password123

## Architecture du Code
server.py : Gère les sockets en mode non-bloquant. Utilise une boucle d'événements (select) pour surveiller les nouvelles connexions, les flux SSH entrants, et les retours du processus système local.

client.py : Établit la connexion TCP, superpose la couche cryptographique SSH, et lance deux threads distincts : l'un pour capturer l'entrée standard (sys.stdin), l'autre en daemon pour écouter le canal SSH de manière asynchrone.

## Autrices
Graciella ISHIMWE
Fathia ABDOURAHMAN MOHAMED
Millisa 