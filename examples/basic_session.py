"""Basic synchronous usage: create a session, send a prompt, print the result id.

Run against a live server, e.g.:

    kilo serve --port 4096 &
    python examples/basic_session.py
"""

from kilocode_client import SyncKilo


def main(base_url: str = "http://127.0.0.1:4096") -> None:
    client = SyncKilo(base_url=base_url)
    session = client.session.create(title="basic-session-example")
    print("created session:", session.id)

    msg = client.send_prompt(session.id, "Reply with the single word: hello")
    print("sent message:", msg.info.id)

    history = client.session.messages(session.id)
    print("message count:", len(history))
    print("todos:", client.session.todo(session.id))

    client.delete_session(session.id)
    print("deleted session")
    client.close()


if __name__ == "__main__":
    main()