import importlib

modules = [
    'rental_app.gmail_core',
    'rental_app.ocr',
    'rental_app.classifier',
    'rental_app.packager',
    'rental_app.gmail_pipeline',
    'scripts.worker'
]


def test_imports():
    for m in modules:
        importlib.import_module(m)
