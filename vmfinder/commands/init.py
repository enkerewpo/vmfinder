"""Initialize VMFinder command."""

import sys
from pathlib import Path

from vmfinder.config import Config
from vmfinder.template import TemplateManager as TM
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_init(args):
    """Initialize VMFinder with default templates."""
    config = Config()
    logger.info(f"Initializing VMFinder in {config.config_dir}...")

    # Create default templates
    TM.create_default_templates(config.templates_dir)

    logger.info(f"✓ Created configuration directory: {config.config_dir}")
    logger.info(f"✓ Created templates directory: {config.templates_dir}")
    logger.info(f"✓ Created default OS templates")
    print(
        "\nYou can now create VMs using: vmfinder vm create <name> --template <template>"
    )
