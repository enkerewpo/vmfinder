"""Install tab completion command."""

import sys
from pathlib import Path

from vmfinder.logger import get_logger

logger = get_logger()


def cmd_install_completion(args):
    """Install tab completion for vmfinder."""
    try:
        import argcomplete
    except ImportError:
        logger.error("argcomplete is not installed. Install it with: pip install argcomplete")
        sys.exit(1)
    
    home = Path.home()
    registered = False
    
    # Register for bash
    try:
        bash_completion_dir = home / '.bash_completion.d'
        bash_completion_dir.mkdir(parents=True, exist_ok=True)
        
        completion_script = bash_completion_dir / 'vmfinder'
        with open(completion_script, 'w') as f:
            f.write("""# Bash completion for vmfinder
eval "$(register-python-argcomplete vmfinder)"
""")
        completion_script.chmod(0o644)
        
        # Try to add source line to .bashrc
        bashrc_path = home / '.bashrc'
        source_line = f'source {bash_completion_dir}/*'
        if bashrc_path.exists():
            with open(bashrc_path, 'r') as f:
                bashrc_content = f.read()
            
            if source_line not in bashrc_content and '.bash_completion.d' not in bashrc_content:
                with open(bashrc_path, 'a') as f:
                    f.write(f'\n# Load bash completion\n{source_line}\n')
                logger.info(f"✓ Added completion source to {bashrc_path}")
                print(f"✓ Added completion source to {bashrc_path}")
        else:
            # Create .bashrc if it doesn't exist
            with open(bashrc_path, 'w') as f:
                f.write(f'# Bash completion\n{source_line}\n')
            logger.info(f"✓ Created {bashrc_path} with completion")
            print(f"✓ Created {bashrc_path} with completion")
        
        logger.info(f"✓ Registered bash completion at {completion_script}")
        print(f"✓ Bash completion installed at {completion_script}")
        registered = True
    except Exception as e:
        logger.warning(f"Could not register bash completion: {e}")
    
    # Register for zsh
    try:
        zshrc_path = home / '.zshrc'
        completion_line = 'eval "$(register-python-argcomplete vmfinder)"'
        
        if zshrc_path.exists():
            with open(zshrc_path, 'r') as f:
                content = f.read()
            
            if 'register-python-argcomplete vmfinder' not in content:
                with open(zshrc_path, 'a') as f:
                    f.write(f'\n# VMFinder tab completion\n{completion_line}\n')
                logger.info(f"✓ Added zsh completion to {zshrc_path}")
                print(f"\nZsh completion added to {zshrc_path}")
                registered = True
            else:
                logger.info(f"Zsh completion already registered in {zshrc_path}")
                print(f"\nZsh completion already registered in {zshrc_path}")
                registered = True
        else:
            print(f"\n{zshrc_path} not found. Add the following to enable zsh completion:")
            print(f"  {completion_line}")
    except Exception as e:
        logger.warning(f"Could not register zsh completion: {e}")
    
    if registered:
        print("\n✓ Tab completion installed!")
        print("Restart your terminal or run:")
        print("  source ~/.bashrc  # for bash")
        print("  source ~/.zshrc   # for zsh")
    else:
        logger.error("Failed to register completion for any shell")
        sys.exit(1)

