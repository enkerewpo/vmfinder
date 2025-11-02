"""Template management commands."""

import sys
from tabulate import tabulate

from vmfinder.config import Config
from vmfinder.template import TemplateManager
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_template_list(args):
    """List all available templates."""
    config = Config()
    manager = TemplateManager(config.templates_dir)
    templates = manager.list_templates()
    
    if not templates:
        logger.warning("No templates found. Run 'vmfinder init' to create default templates.")
        return
    
    headers = ['Name', 'OS', 'Version', 'Arch', 'Description']
    rows = [[t['name'], t['os'], t['version'], t['arch'], t['description']] 
            for t in templates]
    print(tabulate(rows, headers=headers, tablefmt='grid'))


def cmd_template_create(args):
    """Create a new template."""
    config = Config()
    manager = TemplateManager(config.templates_dir)
    
    template = {
        'os': args.os,
        'version': args.version,
        'os_type': 'hvm',
        'os_variant': args.os_variant or f"{args.os}{args.version}",
        'arch': args.arch,
        'boot': 'hd',
        'description': args.description or f"{args.os} {args.version}",
    }
    
    # Set cloud image support if specified or if URL is provided
    if args.cloud_image_support is not None:
        template['cloud_image_support'] = args.cloud_image_support
    elif args.cloud_image_url:
        template['cloud_image_support'] = True
    
    # Set cloud image URL if provided
    if args.cloud_image_url:
        template['cloud_image_url'] = args.cloud_image_url
    
    manager.create_template(args.name, template)
    logger.info(f"✓ Created template: {args.name}")

