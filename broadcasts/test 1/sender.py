import socket
import time
import cryptocode as cc

BROADCAST_IP = '255.255.255.255'
PORT = 12345
MESSAGE = cc.encrypt("Hi", "pwd")

def send_broadcast_message():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    print(f"Отправка широковещательных сообщений на {BROADCAST_IP}:{PORT}")

    try:
        while True:
            sock.sendto(MESSAGE.encode('utf-8'), (BROADCAST_IP, PORT))
            print(f"Отправлено: '{MESSAGE}'")
            time.sleep(2)
    except KeyboardInterrupt:
        print("Отправка сообщений остановлена.")
    finally:
        sock.close()

if __name__ == "__main__":
    send_broadcast_message()