from app import create_app
import webbrowser
from threading import Timer

app = create_app()


def open_browser():
    webbrowser.open("http://127.0.0.1:5000/")


if __name__ == "__main__":
    # Open Chrome after the Flask server starts
    Timer(1, open_browser).start()

    # Avoid importing the app twice when the Windows debug reloader starts.
    app.run(debug=True, use_reloader=False)
