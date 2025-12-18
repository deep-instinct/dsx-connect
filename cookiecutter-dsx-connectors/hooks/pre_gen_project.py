import re
import sys
import subprocess

MODULE_REGEX = r'^[_a-zA-Z][_a-zA-Z0-9]+$'

module_name = '{{ cookiecutter.project_slug }}'

if not re.match(MODULE_REGEX, module_name):
    print('ERROR: The project slug (%s) is not a valid Python module name. '
          'Please do not use a - and use _ instead' % module_name)
    #Exit to cancel project
    sys.exit(1)

# def is_docker_installed() -> bool:
#     try:
#         subprocess.run(["docker", "--version"], capture_output=True, check=True)
#         return True
#     except Exception:
#         return False
#
# if __name__ == "__main__":
#     if not is_docker_installed():
#         print("ERROR: Docker is not installed.")
#         sys.exit(1)
#     else:
#         print("Docker installed... continuing.")
