import socket
import cryptocode as cc

PORT = 12345
BUFFER_SIZE = 1024

def receive_broadcast_message():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind(('', PORT))
    except socket.error as e:
        print(f"Не удалось привязаться к порту {PORT}: {e}")
        print("Возможно, порт уже занят или брандмауэр блокирует.")
        return

    print(f"Ожидание широковещательных сообщений на порту {PORT}...")

    try:
        while True:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            message = data.decode('utf-8')
            print(f"Получено от {addr}: {cc.decrypt(message, 'pwd')}")
    except KeyboardInterrupt:
        print("Прием сообщений остановлен.")
    finally:
        sock.close()

if __name__ == "__main__":
    receive_broadcast_message()