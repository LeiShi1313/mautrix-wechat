from mautrix.util.logging.color import PREFIX, RESET, ColorFormatter as BaseColorFormatter

HANGUPS_COLOR = PREFIX + "35;1m"  # magenta


class ColorFormatter(BaseColorFormatter):
    def _color_name(self, module: str) -> str:
        if module.startswith("wesdk"):
            return HANGUPS_COLOR + module + RESET
        return super()._color_name(module)