import socket
import threading
import json

HOST = '0.0.0.0'  # Yerel ağda oynamak için buraya kendi yerel IP adresini (örn: 192.168.1.X) yazmalısın.
PORT = 5555
WORLD_SEED = 42  # İki oyuncunun da aynı haritayı üretmesi için sabit tohum.

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

try:
    server.bind((HOST, PORT))
except socket.error as e:
    print(f"[HATA] Sunucu baslatilamadi: {e}")
    exit()

server.listen(2)  # 2 kişilik sınır
print(f"[SUNUCU AKTIF] {HOST}:{PORT} uzerinde baglantilar bekleniyor...")

# Oyuncuların anlık verilerini (x, y, hareket durumu) tutacağımız sözlük.
players = {}
current_id = 0


def handle_client(conn, addr, player_id):
    print(f"[YENI BAGLANTI] Oyuncu {player_id} baglandi: {addr}")

    # İstemciye oyuna başlarken kendi ID'sini ve harita Seed'ini gönder.
    init_data = json.dumps({"id": player_id, "seed": WORLD_SEED}) + "\n"
    conn.send(init_data.encode('utf-8'))

    # Oyuncunun başlangıç değerlerini oluştur.
    players[player_id] = {"x": 0, "y": 0, "facing": "down", "moving": False}

    buffer = ""
    while True:
        try:
            data = conn.recv(1024).decode('utf-8')
            if not data:
                break

            buffer += data
            if '\n' in buffer:
                lines = buffer.split('\n')
                buffer = lines[-1]  # Tamamlanmamış parçayı sakla

                # Sadece gelen en son eksiksiz veriyi al
                if lines[-2]:
                    update = json.loads(lines[-2])
                    players[player_id].update(update)

            # Bu oyuncu dışındaki diğer oyuncuların verilerini paketle ve yolla
            other_players = {k: v for k, v in players.items() if k != player_id}
            out_data = json.dumps(other_players) + "\n"
            conn.send(out_data.encode('utf-8'))

        except Exception as e:
            print(f"[HATA] Oyuncu {player_id} ile iletisim kesildi: {e}")
            break

    print(f"[BAGLANTI KOPTU] Oyuncu {player_id} ayrildi.")
    if player_id in players:
        del players[player_id]
    conn.close()


while True:
    conn, addr = server.accept()
    thread = threading.Thread(target=handle_client, args=(conn, addr, current_id), daemon=True)
    thread.start()
    current_id += 1