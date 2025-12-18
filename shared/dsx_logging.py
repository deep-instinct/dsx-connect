# dsx_connect/ops_logging.py
import os
import logging
import colorlog

_LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "bold_red",
    "CRITICAL": "bold_red,bg_white",
}

_DEFAULT_FMT = "%(log_color)s%(asctime)s %(levelname)-8s %(filename)-20s: %(message)s"
_ERROR_FMT = "%(log_color)s%(asctime)s %(levelname)-8s %(filename)-20s:%(lineno)d: %(message)s"


class _LevelSwitchingHandler(logging.StreamHandler):
    def __init__(self):
        super().__init__()
        self._default = colorlog.ColoredFormatter(_DEFAULT_FMT, log_colors=_LOG_COLORS)
        self._error = colorlog.ColoredFormatter(_ERROR_FMT, log_colors=_LOG_COLORS)

    def emit(self, record: logging.LogRecord) -> None:
        # Pick format dynamically
        self.setFormatter(self._error if record.levelno >= logging.ERROR else self._default)
        super().emit(record)


def configure_ops_logging(
        name: str = "dsx-connect",
        env_var: str = "LOG_LEVEL",
        syslog_host_env: str = "SYSLOG_HOST",
        syslog_port_env: str = "SYSLOG_PORT",
) -> logging.Logger:
    """
    Configure a classic stdlib logger for operational logs.
    - Color console output matching your current style
    - Optional syslog fan-out if SYSLOG_HOST/SYSLOG_PORT are set
    """
    level = os.getenv(env_var, "INFO").upper()
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.propagate = False

    # Console
    if not any(isinstance(h, _LevelSwitchingHandler) for h in logger.handlers):
        logger.addHandler(_LevelSwitchingHandler())

    # Optional syslog (UDP 514 by default)
    syslog_host = os.getenv(syslog_host_env)
    syslog_port = int(os.getenv(syslog_port_env, "514")) if os.getenv(syslog_host_env) else None
    if syslog_host and syslog_port:
        sh = logging.handlers.SysLogHandler(address=(syslog_host, syslog_port))
        sh.setFormatter(logging.Formatter("%(message)s"))  # payload already formatted above
        logger.addHandler(sh)

    logger.info(f"Log level set to {level}")
    if syslog_host and syslog_port:
        logger.info(f"Syslog enabled → {syslog_host}:{syslog_port}")

    return logger


# Convenience singleton for quick imports:
dsx_logging = configure_ops_logging()

# import os
#
# import sys
# import logging
# import colorlog
#
# dsx_logging = logging.getLogger("dpa-proxy")
# log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
# dsx_logging.setLevel(level=log_level)
# dsx_logging.propagate = False  # Prevent the logger from propagating messages to the root logger
#
#
# # Define colors for each log level
# log_colors = {
#     'DEBUG': 'cyan',
#     'INFO': 'green',
#     'WARNING': 'yellow',
#     'ERROR': 'bold_red',
#     'CRITICAL': 'bold_red,bg_white',
# }
#
# log_format = '%(log_color)s%(asctime)s %(levelname)-8s %(filename)-20s: %(message)s'
# error_format = '%(log_color)s%(asctime)s %(levelname)-8s %(filename)-20s:%(lineno)d: %(message)s'
#
# # Create a color formatter
# # formatter = colorlog.ColoredFormatter(log_format, log_colors=log_colors)
#
# # Create the formatters using ColoredFormatter
# default_formatter = colorlog.ColoredFormatter(log_format, log_colors=log_colors)
# error_formatter = colorlog.ColoredFormatter(error_format, log_colors=log_colors)
#
#
# # Create a custom handler to switch formatters based on log level
# class CustomLogHandler(logging.StreamHandler):
#     def emit(self, record):
#         # Use the error formatter for error and higher levels, otherwise use the default formatter
#         if record.levelno >= logging.ERROR:
#             self.setFormatter(error_formatter)
#         else:
#             self.setFormatter(default_formatter)
#         super().emit(record)
#
# # Add the custom handler to the logger
# if not dsx_logging.handlers:
#     custom_handler = CustomLogHandler()
#     dsx_logging.addHandler(custom_handler)
# # Create a console handler with the specified format
# # Create and add the console handler if it doesn't already exist
# if not dsx_logging.handlers:
#     custom_handler = CustomLogHandler()
#     dsx_logging.addHandler(custom_handler)
#     # console_handler = logging.StreamHandler()
#     # console_handler.setFormatter(formatter)
#     # dpx_logging.addHandler(console_handler)
#
# dsx_logging.info(f'Log level set to {log_level}')
