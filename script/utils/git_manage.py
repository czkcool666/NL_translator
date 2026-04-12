import os
import subprocess
import logging

class GitManager:

    def ensure_git_repo(self, repo_path):
        git_dir = os.path.join(repo_path, '.git')
        if not os.path.exists(git_dir):
            try:
                current_dir = os.getcwd()
                os.chdir(repo_path)
            
                subprocess.run(
                    ["git", "init"],
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                subprocess.run(
                    ["git", "add", "."],
                    check=True,
                    capture_output=True,
                    text=True
                )
                subprocess.run(
                    ["git", "commit", "-m", "Initial commit"],
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                os.chdir(current_dir)
                return True
            except subprocess.CalledProcessError as e:
                if current_dir != os.getcwd():
                    os.chdir(current_dir)
                return False
        return True

    def git_save_state(self, repo_path, message):
        try:
            current_dir = os.getcwd()
            os.chdir(repo_path)
            
            subprocess.run(
                ["git", "add", "."],
                check=True,
                capture_output=True,
                text=True
            )
            
            result = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0 and "nothing to commit" not in result.stderr:
                logging.warning(f"Git commit failed: {result.stderr}")
                os.chdir(current_dir)
                return None
            
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True
            )
            commit_hash = result.stdout.strip()
            
            logging.info(f"Git commit created: {commit_hash[:8]} - {message}")
            
            os.chdir(current_dir)
            return commit_hash
        except subprocess.CalledProcessError as e:
            logging.error(f"Git save state failed: {e}")
            if current_dir != os.getcwd():
                os.chdir(current_dir)
            return None

    def git_restore_state(self, repo_path, commit_hash):
        try:
            current_dir = os.getcwd()
            os.chdir(repo_path)
            
            subprocess.run(
                ["git", "reset", "--hard", commit_hash],
                check=True,
                capture_output=True,
                text=True
            )
            
            logging.info(f"Git restore state: {commit_hash[:8]}")
            
            os.chdir(current_dir)
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Git restore state failed: {e}")
            if current_dir != os.getcwd():
                os.chdir(current_dir)
            return False