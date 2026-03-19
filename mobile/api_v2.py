# Mobile API Implementation

from flask import Flask, jsonify, request

app = Flask(__name__)

# Sample data structure
items = [
    {'id': 1, 'name': 'Item 1'},
    {'id': 2, 'name': 'Item 2'}
]

@app.route('/api/v2/items', methods=['GET'])
def get_items():
    """Get all items"""
    return jsonify(items)

@app.route('/api/v2/items/<int:item_id>', methods=['GET'])
def get_item(item_id):
    """Get a single item by id"""
    item = next((item for item in items if item['id'] == item_id), None)
    return jsonify(item) if item else ('', 404)

@app.route('/api/v2/items', methods=['POST'])
def create_item():
    """Create a new item"""
    if not request.json or 'name' not in request.json:
        return jsonify({'error': 'Bad Request'}), 400
    item = {
        'id': items[-1]['id'] + 1,
        'name': request.json['name']
    }
    items.append(item)
    return jsonify(item), 201

@app.route('/api/v2/items/<int:item_id>', methods=['PUT'])
def update_item(item_id):
    """Update an existing item"""
    item = next((item for item in items if item['id'] == item_id), None)
    if item is None:
        return ('', 404)
    if not request.json:
        return jsonify({'error': 'Bad Request'}), 400
    item['name'] = request.json.get('name', item['name'])
    return jsonify(item)

@app.route('/api/v2/items/<int:item_id>', methods=['DELETE'])
def delete_item(item_id):
    """Delete an item"""
    global items
    items = [item for item in items if item['id'] != item_id]
    return ('', 204)

if __name__ == '__main__':
    app.run(debug=True)
