import os
print("Template path:", os.path.join(app.root_path, 'templates'))
print("Files:", os.listdir(os.path.join(app.root_path, 'templates')))
