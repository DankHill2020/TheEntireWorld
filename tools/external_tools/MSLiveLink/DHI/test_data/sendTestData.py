import socket
import json

HOST, PORT = "localhost", 13291


def load_json_data_from_file(filename):
    with open(filename) as json_file:
        data = json.load(json_file)
        return json.dumps(data)


def send_to_importer(data):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Connect to server and send data
        print("Connecting to socket %s %s" % (HOST, PORT))
        sock.connect((HOST, PORT))
        print("Connected... sending data...")
        sock.sendall(data.encode())
        print("Data sent")
    except Exception as e:
        print("Caught exception socket.error : %s" % e)
        print("Error connecting to socket")
        pass
    finally:
        sock.close()
        quit()


data = load_json_data_from_file('sample_002.json')
send_to_importer(data)
