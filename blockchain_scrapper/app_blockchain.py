from flask import Flask, request, jsonify, send_file, render_template_string
import os
from blockchain import Blockchain

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))

DATA_FILE = os.path.join(os.path.dirname(__file__), "blockchain_data.json")
bc = Blockchain(difficulty=3)
if os.path.exists(DATA_FILE):
    try:
        bc = Blockchain.load_from_file(DATA_FILE, difficulty=3)
    except Exception as e:
        print("Could not load existing blockchain file:", e)

@app.route('/', methods=['GET'])
def home():
    return "Blockchain API - endpoints: /chain, /add (POST JSON), /validate, /download, /history"

@app.route('/chain', methods=['GET'])
def get_chain():
    return jsonify(bc.to_list()), 200

@app.route('/add', methods=['POST'])
def add_block():
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON body must be an object/dict'}), 400
    # allow duplicates as requested
    block = bc.add_block(data)
    bc.save_to_file(DATA_FILE)
    return jsonify(block.to_dict()), 201

@app.route('/validate', methods=['GET'])
def validate_chain():
    valid, message = bc.is_chain_valid()
    return jsonify({'valid': valid, 'message': message}), 200

@app.route('/download', methods=['GET'])
def download_chain():
    if not os.path.exists(DATA_FILE):
        bc.save_to_file(DATA_FILE)
    return send_file(DATA_FILE, as_attachment=True)

@app.route('/history', methods=['GET'])
def history():
    blocks = bc.to_list()
    html_template = """    <!doctype html>
<html>
<head><meta charset='utf-8'><title>Blockchain History</title>
<style>table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:8px;text-align:left}th{background:#f4f4f4}</style>
</head><body>
<h2>Blockchain History</h2>
<table>
<tr><th>Index</th><th>Timestamp</th><th>Data</th><th>Hash</th><th>Previous Hash</th></tr>
{% for b in blocks %}
<tr>
  <td>{{ b.index }}</td>
  <td>{{ b.timestamp }}</td>
  <td>
    {% for k,v in b.data.items() %}<strong>{{ k }}</strong>: {{ v }}<br>{% endfor %}
  </td>
  <td>{{ b.hash }}</td>
  <td>{{ b.previous_hash }}</td>
</tr>
{% endfor %}
</table>
</body></html>
"""
    from types import SimpleNamespace
    blocks_ns = [SimpleNamespace(**b) for b in blocks]
    return render_template_string(html_template, blocks=blocks_ns)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
