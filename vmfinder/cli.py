"""Command-line interface for VMFinder."""

import argparse
import sys
import os
from pathlib import Path

# Try to import argcomplete for tab completion
try:
    import argcomplete

    ARGCOMPLETE_AVAILABLE = True
except ImportError:
    ARGCOMPLETE_AVAILABLE = False

from vmfinder import (
    __version__,
    __author__,
    __author_email__,
    __url__,
    __description__,
    __copyright__,
)
from vmfinder.config import Config
from vmfinder.logger import setup_logger, get_logger
from vmfinder.completion import (
    complete_vm_name,
    complete_template_name,
    complete_network_name,
    complete_file_path,
)

# Import command modules
from vmfinder.commands import init as cmd_init
from vmfinder.commands import template as cmd_template
from vmfinder.commands import install_completion as cmd_install_completion
from vmfinder.commands import virtiofs as cmd_virtiofs
from vmfinder.commands.vm import (
    cmd_vm_list,
    cmd_vm_start,
    cmd_vm_stop,
    cmd_vm_suspend,
    cmd_vm_resume,
    cmd_vm_restart,
    cmd_vm_create,
    cmd_vm_delete,
    cmd_vm_info,
    cmd_vm_set_cpu,
    cmd_vm_set_memory,
    cmd_vm_fix_permissions,
    cmd_vm_resize_disk,
    cmd_vm_console,
    cmd_vm_ssh,
    cmd_vm_set_password,
    cmd_vm_fix_cloud_init,
)


class VersionAction(argparse.Action):
    """Custom action to print version information in multiple lines with logo."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def _make_link(self, url, text=None):
        """Create a clickable hyperlink using OSC 8 escape sequence."""
        if text is None:
            text = url
        # OSC 8 escape sequence: \033]8;;URL\033\\TEXT\033]8;;\033\\
        return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"

    def __call__(self, parser, namespace, values, option_string=None):
        # Furry logo ASCII art (fox)
        logo = [
            "    /\\_/\\  ",
            "   ( o.o ) ",
            "    > ^ <  ",
            "   /     \\ ",
            "  (   V   )",
            "   \\_____/ ",
        ]

        COLOR_YELLOW = "\033[33m"
        COLOR_BOLD = "\033[1m"
        COLOR_RESET = "\033[0m"

        # Version info lines
        info_lines = [
            f"{COLOR_YELLOW}{COLOR_BOLD}{parser.prog} {__version__}{COLOR_RESET}",
            "",
            f"{COLOR_BOLD}{__description__}{COLOR_RESET}",
            "",
            f"Author: {__author__} <{__author_email__}>",
            f"URL: {self._make_link(__url__)}",
            __copyright__,
        ]

        # Get logo width for consistent spacing
        logo_width = max(len(line) for line in logo) if logo else 0

        # Combine logo and info in side-by-side layout
        max_logo_height = len(logo)
        max_info_height = len(info_lines)
        max_height = max(max_logo_height, max_info_height)

        output_lines = []
        for i in range(max_height):
            logo_line = logo[i] if i < len(logo) else ""
            logo_padded = logo_line.ljust(logo_width) if logo_line else " " * logo_width
            info_line = info_lines[i] if i < len(info_lines) else ""
            output_lines.append(f"{logo_padded}  {info_line}")

        print("\n".join(output_lines))
        parser.exit()


def create_parser():
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="vmfinder",
        description=__description__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global options
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress non-error output"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )
    log_file_arg = parser.add_argument(
        "--log-file", type=Path, help="Log to file instead of stdout"
    )
    if ARGCOMPLETE_AVAILABLE:
        log_file_arg.completer = complete_file_path

    parser.add_argument(
        "--version", action=VersionAction, help="Show version information and exit"
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init command
    parser_init = subparsers.add_parser(
        "init", help="Initialize VMFinder with default templates"
    )
    parser_init.set_defaults(func=cmd_init.cmd_init)

    # install-completion command
    parser_install_comp = subparsers.add_parser(
        "install-completion", help="Install tab completion for bash and zsh"
    )
    parser_install_comp.set_defaults(func=cmd_install_completion.cmd_install_completion)

    # template commands
    parser_template = subparsers.add_parser("template", help="Manage VM templates")
    template_subparsers = parser_template.add_subparsers(
        dest="template_command", help="Template commands"
    )

    parser_template_list = template_subparsers.add_parser(
        "list", help="List all available templates"
    )
    parser_template_list.set_defaults(func=cmd_template.cmd_template_list)

    parser_template_update = template_subparsers.add_parser(
        "update", help="Update templates to default templates"
    )
    parser_template_update.set_defaults(func=cmd_template.cmd_template_update)

    parser_template_create = template_subparsers.add_parser(
        "create", help="Create a new template"
    )
    parser_template_create.add_argument("name", help="Template name")
    parser_template_create.add_argument(
        "--os", required=True, help="Operating system name"
    )
    parser_template_create.add_argument("--version", required=True, help="OS version")
    parser_template_create.add_argument("--os-variant", help="OS variant for libvirt")
    parser_template_create.add_argument(
        "--arch", default="x86_64", help="Architecture (default: x86_64)"
    )
    parser_template_create.add_argument("--description", help="Template description")
    parser_template_create.add_argument(
        "--cloud-image-url", help="Cloud image URL for auto-install"
    )
    parser_template_create.add_argument(
        "--cloud-image-support", action="store_true", help="Enable cloud image support"
    )
    parser_template_create.add_argument(
        "--no-cloud-image-support",
        dest="cloud_image_support",
        action="store_false",
        help="Disable cloud image support",
    )
    parser_template_create.set_defaults(func=cmd_template.cmd_template_create)

    # vm commands
    parser_vm = subparsers.add_parser("vm", help="Manage virtual machines")
    vm_subparsers = parser_vm.add_subparsers(dest="vm_command", help="VM commands")

    # vm list
    parser_vm_list = vm_subparsers.add_parser("list", help="List all virtual machines")
    parser_vm_list.set_defaults(func=cmd_vm_list)

    # vm create
    parser_vm_create = vm_subparsers.add_parser(
        "create", help="Create a new virtual machine"
    )
    parser_vm_create.add_argument("name", help="VM name")
    template_arg = parser_vm_create.add_argument(
        "--template", "-t", required=True, help="Template name"
    )
    if ARGCOMPLETE_AVAILABLE:
        template_arg.completer = complete_template_name
    parser_vm_create.add_argument(
        "--cpu", "-c", type=int, default=2, help="Number of CPUs (default: 2)"
    )
    parser_vm_create.add_argument(
        "--memory", "-m", type=int, default=2048, help="Memory in MB (default: 2048)"
    )
    parser_vm_create.add_argument(
        "--disk-size", "-d", type=int, default=20, help="Disk size in GB (default: 20)"
    )
    network_arg = parser_vm_create.add_argument(
        "--network", default="default", help="Network name (default: default)"
    )
    if ARGCOMPLETE_AVAILABLE:
        network_arg.completer = complete_network_name
    parser_vm_create.add_argument(
        "--auto-install",
        action="store_true",
        default=True,
        help="Automatically install OS from cloud image (default: enabled)",
    )
    parser_vm_create.add_argument(
        "--no-auto-install",
        dest="auto_install",
        action="store_false",
        help="Disable auto-install",
    )
    parser_vm_create.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force overwrite existing VM without prompting",
    )
    parser_vm_create.add_argument(
        "--virtiofs",
        help="Mount host directory via virtio-fs (path to host directory)",
    )
    parser_vm_create.add_argument(
        "--virtiofs-tag",
        default="shared",
        help="Mount tag name for virtio-fs (default: shared)",
    )
    parser_vm_create.set_defaults(func=cmd_vm_create)

    # vm start
    parser_vm_start = vm_subparsers.add_parser("start", help="Start a virtual machine")
    vm_start_name = parser_vm_start.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_start_name.completer = complete_vm_name
    parser_vm_start.set_defaults(func=cmd_vm_start)

    # vm stop
    parser_vm_stop = vm_subparsers.add_parser("stop", help="Stop a virtual machine")
    vm_stop_name = parser_vm_stop.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_stop_name.completer = complete_vm_name
    parser_vm_stop.add_argument(
        "--force", "-f", action="store_true", help="Force stop (destroy)"
    )
    parser_vm_stop.add_argument(
        "--kill", "-k", action="store_true", 
        help="Force kill VM immediately (skip graceful shutdown, kill qemu process if needed)"
    )
    parser_vm_stop.set_defaults(func=cmd_vm_stop)

    # vm suspend
    parser_vm_suspend = vm_subparsers.add_parser(
        "suspend", help="Suspend a virtual machine"
    )
    vm_suspend_name = parser_vm_suspend.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_suspend_name.completer = complete_vm_name
    parser_vm_suspend.set_defaults(func=cmd_vm_suspend)

    # vm resume
    parser_vm_resume = vm_subparsers.add_parser(
        "resume", help="Resume a suspended virtual machine"
    )
    vm_resume_name = parser_vm_resume.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_resume_name.completer = complete_vm_name
    parser_vm_resume.set_defaults(func=cmd_vm_resume)

    # vm restart
    parser_vm_restart = vm_subparsers.add_parser(
        "restart", help="Restart a virtual machine"
    )
    vm_restart_name = parser_vm_restart.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_restart_name.completer = complete_vm_name
    parser_vm_restart.add_argument(
        "--force", "-f", action="store_true", help="Force stop (destroy) before restart"
    )
    parser_vm_restart.set_defaults(func=cmd_vm_restart)

    # vm delete
    parser_vm_delete = vm_subparsers.add_parser(
        "delete", help="Delete a virtual machine"
    )
    vm_delete_name = parser_vm_delete.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_delete_name.completer = complete_vm_name
    parser_vm_delete.add_argument(
        "--delete-disk", action="store_true", help="Also delete the disk image"
    )
    parser_vm_delete.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )
    parser_vm_delete.set_defaults(func=cmd_vm_delete)

    # vm info
    parser_vm_info = vm_subparsers.add_parser(
        "info", help="Show detailed information about a virtual machine"
    )
    vm_info_name = parser_vm_info.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_info_name.completer = complete_vm_name
    parser_vm_info.set_defaults(func=cmd_vm_info)

    # vm fix-cloud-init
    parser_vm_fix_cloud_init = vm_subparsers.add_parser(
        "fix-cloud-init", help="Fix cloud-init metadata service warnings"
    )
    vm_fix_ci_name = parser_vm_fix_cloud_init.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_fix_ci_name.completer = complete_vm_name
    parser_vm_fix_cloud_init.add_argument(
        "--start", action="store_true", help="Start VM after fixing cloud-init"
    )
    parser_vm_fix_cloud_init.add_argument(
        "--no-start",
        dest="start",
        action="store_false",
        help="Do not start VM after fixing",
    )
    parser_vm_fix_cloud_init.set_defaults(start=False, func=cmd_vm_fix_cloud_init)

    # vm set-cpu
    parser_vm_set_cpu = vm_subparsers.add_parser(
        "set-cpu", help="Set CPU count for a virtual machine"
    )
    vm_set_cpu_name = parser_vm_set_cpu.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_set_cpu_name.completer = complete_vm_name
    parser_vm_set_cpu.add_argument("cpu", type=int, help="CPU count")
    parser_vm_set_cpu.set_defaults(func=cmd_vm_set_cpu)

    # vm set-memory
    parser_vm_set_memory = vm_subparsers.add_parser(
        "set-memory", help="Set memory for a virtual machine"
    )
    vm_set_mem_name = parser_vm_set_memory.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_set_mem_name.completer = complete_vm_name
    parser_vm_set_memory.add_argument("memory", type=int, help="Memory in MB")
    parser_vm_set_memory.set_defaults(func=cmd_vm_set_memory)

    # vm console
    parser_vm_console = vm_subparsers.add_parser(
        "console", help="Show console command for a virtual machine"
    )
    vm_console_name = parser_vm_console.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_console_name.completer = complete_vm_name
    parser_vm_console.set_defaults(func=cmd_vm_console)

    # vm set-password
    parser_vm_set_password = vm_subparsers.add_parser(
        "set-password", help="Set password for a VM using cloud-init"
    )
    vm_set_pwd_name = parser_vm_set_password.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_set_pwd_name.completer = complete_vm_name
    parser_vm_set_password.add_argument(
        "--username",
        "-u",
        default="ubuntu",
        help="Username to set password for (default: ubuntu)",
    )
    parser_vm_set_password.add_argument(
        "--password", "-p", help="Password to set (prompts if not provided)"
    )
    parser_vm_set_password.add_argument(
        "--start",
        action="store_true",
        default=True,
        help="Start VM after setting password (default: start)",
    )
    parser_vm_set_password.add_argument(
        "--no-start",
        dest="start",
        action="store_false",
        help="Do not start VM after setting password",
    )
    parser_vm_set_password.set_defaults(func=cmd_vm_set_password)

    # vm ssh
    parser_vm_ssh = vm_subparsers.add_parser("ssh", help="Connect to a VM via SSH")
    vm_ssh_name = parser_vm_ssh.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_ssh_name.completer = complete_vm_name
    parser_vm_ssh.add_argument(
        "--username", "-u", default="ubuntu", help="SSH username (default: ubuntu)"
    )
    parser_vm_ssh.add_argument(
        "--port", "-p", type=int, default=22, help="SSH port (default: 22)"
    )
    key_arg = parser_vm_ssh.add_argument(
        "--key", "-k", help="SSH private key file path"
    )
    if ARGCOMPLETE_AVAILABLE:
        key_arg.completer = complete_file_path
    parser_vm_ssh.set_defaults(func=cmd_vm_ssh)

    # vm fix-permissions
    parser_vm_fix_permissions = vm_subparsers.add_parser(
        "fix-permissions", help="Fix disk permissions for a VM"
    )
    vm_fix_perm_name = parser_vm_fix_permissions.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_fix_perm_name.completer = complete_vm_name
    parser_vm_fix_permissions.set_defaults(func=cmd_vm_fix_permissions)

    # vm resize-disk
    parser_vm_resize_disk = vm_subparsers.add_parser(
        "resize-disk", help="Resize a VM's disk image file"
    )
    vm_resize_name = parser_vm_resize_disk.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        vm_resize_name.completer = complete_vm_name
    parser_vm_resize_disk.add_argument("size", type=int, help="New disk size in GB")
    parser_vm_resize_disk.set_defaults(func=cmd_vm_resize_disk)

    # virtiofs commands
    parser_virtiofs = subparsers.add_parser("virtiofs", help="Manage virtio-fs daemons")
    virtiofs_subparsers = parser_virtiofs.add_subparsers(
        dest="virtiofs_command", help="VirtioFS commands"
    )

    # virtiofs start
    parser_virtiofs_start = virtiofs_subparsers.add_parser(
        "start", help="Start virtiofsd for a VM"
    )
    virtiofs_start_name = parser_virtiofs_start.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        virtiofs_start_name.completer = complete_vm_name
    parser_virtiofs_start.add_argument(
        "source",
        nargs="?",
        help="Host directory path to share (optional if state exists)",
    )
    parser_virtiofs_start.add_argument(
        "--tag", default="shared", help="Mount tag name (default: shared)"
    )
    parser_virtiofs_start.add_argument(
        "--cache",
        choices=["none", "auto", "always"],
        default="auto",
        help="Cache mode (default: auto)",
    )
    parser_virtiofs_start.add_argument(
        "--xattr",
        choices=["off", "on", "auto"],
        default="auto",
        help="Extended attributes mode (default: auto)",
    )
    parser_virtiofs_start.add_argument(
        "--no-readdirplus",
        dest="readdirplus",
        action="store_false",
        default=True,
        help="Disable readdirplus optimization",
    )
    parser_virtiofs_start.set_defaults(func=cmd_virtiofs.cmd_virtiofs_start)

    # virtiofs stop
    parser_virtiofs_stop = virtiofs_subparsers.add_parser(
        "stop", help="Stop virtiofsd for a VM"
    )
    virtiofs_stop_name = parser_virtiofs_stop.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        virtiofs_stop_name.completer = complete_vm_name
    parser_virtiofs_stop.add_argument(
        "--force", "-f", action="store_true", help="Force kill virtiofsd"
    )
    parser_virtiofs_stop.set_defaults(func=cmd_virtiofs.cmd_virtiofs_stop)

    # virtiofs status
    parser_virtiofs_status = virtiofs_subparsers.add_parser(
        "status", help="Show virtiofsd status"
    )
    virtiofs_status_name = parser_virtiofs_status.add_argument(
        "name", nargs="?", help="VM name (optional, shows all if omitted)"
    )
    if ARGCOMPLETE_AVAILABLE:
        virtiofs_status_name.completer = complete_vm_name
    parser_virtiofs_status.set_defaults(func=cmd_virtiofs.cmd_virtiofs_status)

    # virtiofs restart
    parser_virtiofs_restart = virtiofs_subparsers.add_parser(
        "restart", help="Restart virtiofsd for a VM"
    )
    virtiofs_restart_name = parser_virtiofs_restart.add_argument("name", help="VM name")
    if ARGCOMPLETE_AVAILABLE:
        virtiofs_restart_name.completer = complete_vm_name
    parser_virtiofs_restart.set_defaults(func=cmd_virtiofs.cmd_virtiofs_restart)

    return parser


def main():
    """Main entry point."""
    parser = create_parser()

    # Enable argcomplete if available
    if ARGCOMPLETE_AVAILABLE:
        argcomplete.autocomplete(parser)

    args = parser.parse_args()

    # Setup logging
    log_level = (
        "DEBUG"
        if args.verbose
        else (args.log_level if hasattr(args, "log_level") else "INFO")
    )
    if args.quiet:
        log_level = "ERROR"

    log_file = None
    if hasattr(args, "log_file") and args.log_file:
        log_file = args.log_file
    else:
        # Default log file location
        config = Config()
        log_file = config.config_dir / "vmfinder.log"

    setup_logger("vmfinder", log_level, log_file)
    logger = get_logger()

    # Execute command
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
