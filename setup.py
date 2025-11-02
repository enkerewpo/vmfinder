"""Minimal setup.py for VMFinder - only provides post-install hook for completion registration.

Most configuration is in pyproject.toml. This file only exists to add custom installation
behavior (automatic completion registration).
"""

from setuptools import setup
from setuptools.command.install import install
from pathlib import Path
import os


class PostInstallCommand(install):
    """Post-installation command to register tab completion."""
    
    def run(self):
        """Run the normal installation and then register completion."""
        # Run the normal installation (reads from pyproject.toml)
        install.run(self)
        
        # Register completion
        try:
            self.register_completion()
        except Exception as e:
            print(f"Warning: Could not automatically register tab completion: {e}")
            print("You can manually register it using: vmfinder install-completion")
    
    def register_completion(self):
        """Register argcomplete for vmfinder."""
        try:
            import argcomplete
        except ImportError:
            print("Warning: argcomplete is not installed. Tab completion will not be available.")
            print("Install it with: pip install argcomplete")
            return False
        
        home = Path.home()
        registered = False
        
        # Try to register for bash
        try:
            bash_completion_dir = home / '.bash_completion.d'
            bash_completion_dir.mkdir(exist_ok=True)
            
            completion_script = bash_completion_dir / 'vmfinder'
            with open(completion_script, 'w') as f:
                f.write("""# Bash completion for vmfinder
eval "$(register-python-argcomplete vmfinder)"
""")
            os.chmod(completion_script, 0o644)
            
            # Try to add source line to .bashrc
            bashrc_path = home / '.bashrc'
            source_line = f'source {bash_completion_dir}/*'
            if bashrc_path.exists():
                with open(bashrc_path, 'r') as f:
                    bashrc_content = f.read()
                
                if source_line not in bashrc_content and '.bash_completion.d' not in bashrc_content:
                    with open(bashrc_path, 'a') as f:
                        f.write(f'\n# Load bash completion\n{source_line}\n')
                    print(f"✓ Added completion source to {bashrc_path}")
            else:
                # Create .bashrc if it doesn't exist
                with open(bashrc_path, 'w') as f:
                    f.write(f'# Bash completion\n{source_line}\n')
                print(f"✓ Created {bashrc_path} with completion")
            
            print(f"✓ Registered bash completion at {completion_script}")
            registered = True
        except Exception as e:
            print(f"Warning: Could not register bash completion: {e}")
        
        # Try to register for zsh
        try:
            zshrc_path = home / '.zshrc'
            completion_line = 'eval "$(register-python-argcomplete vmfinder)"'
            
            if zshrc_path.exists():
                with open(zshrc_path, 'r') as f:
                    content = f.read()
                
                if 'register-python-argcomplete vmfinder' not in content:
                    with open(zshrc_path, 'a') as f:
                        f.write(f'\n# VMFinder tab completion\n{completion_line}\n')
                    print(f"✓ Added zsh completion to {zshrc_path}")
                    registered = True
                else:
                    print(f"✓ Zsh completion already registered in {zshrc_path}")
                    registered = True
            else:
                # Don't create .zshrc automatically if it doesn't exist
                print(f"  Note: {zshrc_path} not found. Add the following to enable zsh completion:")
                print(f"    {completion_line}")
        except Exception as e:
            print(f"Warning: Could not register zsh completion: {e}")
        
        if registered:
            print("\nTab completion registered! Restart your terminal or run:")
            print("  source ~/.bashrc  # for bash")
            print("  source ~/.zshrc   # for zsh")
        
        return registered


# Minimal setup() call - most config is in pyproject.toml
# We only specify cmdclass to add our custom install command
setup(
    cmdclass={
        'install': PostInstallCommand,
    },
)

