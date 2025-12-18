import pathlib

tags_metadata = [
    {'name': 'scan', 'description': 'Methods for initiating scans '},
    {'name': 'config', 'description': 'Methods to view and edit configurations'},
    {'name': 'results', 'description': 'Methods to retrieve results'},
    {'name': 'connectors', 'description': 'Methods for use by connectors to queue tasks'}
]

working_path = pathlib.Path().cwd()
root_path = str(pathlib.Path(__file__).parent)
static_path = pathlib.Path(f'{root_path}/static')
template_path = pathlib.Path(f'{root_path}/templates')
conf_path = pathlib.Path(f'{working_path}/conf')
