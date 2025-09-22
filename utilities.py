from werkzeug.security import generate_password_hash

def hash_my_password(password):
    print(generate_password_hash(password))