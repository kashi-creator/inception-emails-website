import os
from flask import Flask, send_from_directory

app = Flask(__name__, static_folder=".", static_url_path="")


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/msp.html")
@app.route("/msp")
def msp():
    return send_from_directory(".", "msp.html")


@app.route("/functional-medicine.html")
@app.route("/functional-medicine")
def functional_medicine():
    return send_from_directory(".", "functional-medicine.html")


@app.route("/property-maintenance.html")
@app.route("/property-maintenance")
def property_maintenance():
    return send_from_directory(".", "property-maintenance.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
