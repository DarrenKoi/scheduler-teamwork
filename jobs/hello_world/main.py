from datetime import datetime


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] Hello World!")
    print("This is a sample job running successfully.")


if __name__ == "__main__":
    main()
