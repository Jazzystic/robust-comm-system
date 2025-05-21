import socket
import threading
import json
import base64
import logging
import os

logging.basicConfig(level=logging.DEBUG)


class ChatServer:
    def __init__(self, host='localhost', port=14999):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.host, self.port))
        self.clients = {}
        self.groups = {}
        self.profile_images = {}
        self.file_chunks = {}
        self.received_files_dir = "received_files"
        os.makedirs(self.received_files_dir, exist_ok=True)

    def start(self):
        self.server_socket.listen(5)
        logging.info(f"Servidor iniciado en {self.host}:{self.port}")
        while True:
            client_socket, address = self.server_socket.accept()
            logging.info(f"Conexión aceptada de {address}")
            threading.Thread(target=self.handle_client, args=(client_socket,)).start()

    def handle_client(self, client_socket):
        try:
            username = client_socket.recv(1024).decode('utf-8')
            if not username:
                raise ValueError("No se recibió un nombre de usuario.")

            logging.info(f"Usuario {username} conectado desde {client_socket.getpeername()}")

            self.clients[username] = client_socket

            profile_image = client_socket.recv(1024 * 1024).decode('utf-8')
            self.profile_images[username] = profile_image

            self.broadcast_user_list()

            buffer = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    raise ConnectionError("Cliente desconectado.")

                logging.debug(f"Recibido chunk de {username}")

                buffer += chunk
                while b'\n' in buffer:
                    message, buffer = buffer.split(b'\n', 1)
                    try:
                        data = json.loads(message.decode('utf-8'))
                        self.process_message(username, data)
                    except json.JSONDecodeError:
                        # Si no es JSON, asumimos que es un chunk de archivo
                        self.handle_file_chunk(username, message)
        except ConnectionError:
            logging.info(f"Usuario {username} desconectado.")
        except Exception as e:
            logging.error(f"Error en la conexión con {username}: {e}")
        finally:
            self.disconnect_client(username)
            client_socket.close()

    def process_message(self, sender, data):
        try:
            if data['type'] == 'message':
                recipient = data['recipient']
                content = data['content']
                if recipient in self.clients:
                    self.send_message(sender, recipient, content)
                elif recipient in self.groups:
                    self.send_group_message(sender, recipient, content)
                else:
                    logging.warning(f"Destinatario desconocido: {recipient}")
            elif data['type'] == 'create_group':
                group_name = data['group_name']
                members = data['members']
                self.create_group(group_name, members)
            elif data['type'] == 'file_chunk':
                self.handle_file_chunk(sender, json.dumps(data).encode('utf-8'))
            elif data['type'] == 'profile_image':
                self.update_profile_image(sender, data['image'])
            elif data['type'] == 'start_video_call':
                recipient = data['recipient']
                if recipient in self.clients:
                    self.send_message(sender, recipient, '[Videollamada iniciada]')
        except Exception as e:
            logging.error(f"Error al procesar el mensaje de {sender}: {e}")

    def send_message(self, sender, recipient, content):
        try:
            message = json.dumps({
                'type': 'message',
                'sender': sender,
                'content': content
            })
            self.clients[recipient].send(message.encode('utf-8') + b'\n')
            logging.info(f"Mensaje enviado de {sender} a {recipient}")
        except Exception as e:
            logging.error(f"Error al enviar el mensaje de {sender} a {recipient}: {e}")

    def send_group_message(self, sender, group, content):
        try:
            message = json.dumps({
                'type': 'group_message',
                'sender': sender,
                'group': group,
                'content': content
            })
            for member in self.groups[group]:
                if member in self.clients and member != sender:
                    self.clients[member].send(message.encode('utf-8') + b'\n')
            logging.info(f"Mensaje grupal enviado de {sender} al grupo {group}")
        except Exception as e:
            logging.error(f"Error al enviar el mensaje grupal de {sender} al grupo {group}: {e}")

    def handle_file_chunk(self, username, chunk):
        try:
            data = json.loads(chunk.decode('utf-8'))
            recipient = data['recipient']
            file_name = data['file_name']
            chunk_number = data['chunk_number']
            total_chunks = data['total_chunks']
            content = base64.b64decode(data['content'])

            if recipient not in self.file_chunks:
                self.file_chunks[recipient] = {}
            if file_name not in self.file_chunks[recipient]:
                self.file_chunks[recipient][file_name] = [None] * total_chunks

            self.file_chunks[recipient][file_name][chunk_number] = content

            if all(self.file_chunks[recipient][file_name]):
                file_content = b"".join(self.file_chunks[recipient][file_name])
                safe_filename = os.path.join(self.received_files_dir, f"received_{file_name}")
                with open(safe_filename, "wb") as f:
                    f.write(file_content)
                full_path = os.path.abspath(safe_filename)
                self.send_message(username, recipient, f"[Archivo recibido: {file_name}]. Guardado en: {full_path}")
                logging.info(f"Archivo {file_name} reensamblado para {recipient} y guardado en {full_path}")
                del self.file_chunks[recipient][file_name]
        except json.JSONDecodeError:
            logging.error(f"Error al decodificar chunk de archivo de {username}")
        except Exception as e:
            logging.error(f"Error al procesar chunk de archivo de {username}: {e}")

    def update_profile_image(self, username, image_data):
        try:
            # Verificar que image_data es una cadena válida en base64
            base64.b64decode(image_data)
            self.profile_images[username] = image_data
            logging.info(f"Imagen de perfil actualizada para {username}")
            self.broadcast_user_list()
        except Exception as e:
            logging.error(f"Error al actualizar la imagen de perfil de {username}: {e}")

    def broadcast_user_list(self):
        try:
            user_list = [{
                'username': username,
                'profile_image': self.profile_images.get(username, '')
            } for username in self.clients.keys()]
            message = json.dumps({
                'type': 'user_list',
                'users': user_list
            })
            for client in self.clients.values():
                client.send(message.encode('utf-8') + b'\n')
            logging.info("Lista de usuarios actualizada y enviada a todos los clientes")
        except Exception as e:
            logging.error(f"Error al enviar la lista de usuarios: {e}")

    def disconnect_client(self, username):
        try:
            if username in self.clients:
                del self.clients[username]
            if username in self.profile_images:
                del self.profile_images[username]
            # Remover al usuario de todos los grupos
            for group_name, members in self.groups.items():
                if username in members:
                    members.remove(username)
                    if not members:  # Si el grupo queda vacío, eliminarlo
                        del self.groups[group_name]
            self.broadcast_user_list()
            self.broadcast_group_list()
            logging.info(f"Cliente {username} desconectado y eliminado")
        except Exception as e:
            logging.error(f"Error al desconectar al cliente {username}: {e}")

    def create_group(self, group_name, members):
        try:
            if group_name not in self.groups:
                self.groups[group_name] = members
                message = json.dumps({
                    'type': 'group_created',
                    'group_name': group_name,
                    'members': members
                })
                for member in members:
                    if member in self.clients:
                        self.clients[member].send(message.encode('utf-8') + b'\n')
                logging.info(f"Grupo '{group_name}' creado con miembros: {', '.join(members)}")
                self.broadcast_group_list()
            else:
                logging.warning(f"Intento de crear un grupo con nombre existente: {group_name}")
        except Exception as e:
            logging.error(f"Error al crear el grupo {group_name}: {e}")

    def broadcast_group_list(self):
        try:
            group_list = list(self.groups.keys())
            message = json.dumps({
                'type': 'group_list',
                'groups': group_list
            })
            for client in self.clients.values():
                client.send(message.encode('utf-8') + b'\n')
            logging.info("Lista de grupos actualizada y enviada a todos los clientes")
        except Exception as e:
            logging.error(f"Error al enviar la lista de grupos: {e}")


if __name__ == "__main__":
    server = ChatServer()
    server.start()
