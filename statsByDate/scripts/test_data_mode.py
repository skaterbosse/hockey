from pathlib import Path

def test_root(parser):
    root = Path(__file__).resolve().parent.parent / 'data_test'
    if not root.is_dir() or root.is_symlink():
        parser.error('Create a real data_test directory from production data first')
    for p in root.rglob('*'):
        if p.is_symlink() or (p.is_file() and p.stat().st_nlink > 1):
            parser.error(f'Unsafe linked test data: {p}')
    return root
