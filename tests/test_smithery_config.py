"""Test script to verify the Smithery configuration is valid."""

import os
import json
import sys
import yaml
from pathlib import Path


def validate_smithery_yaml():
    """Validate the smithery.yaml file."""
    smithery_yaml_path = Path(__file__).parent.parent / "smithery.yaml"
    
    # Check file exists
    if not smithery_yaml_path.exists():
        print("Error: smithery.yaml file not found!")
        return False
    
    try:
        # Load YAML file
        with open(smithery_yaml_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Validate basic structure
        if 'startCommand' not in config:
            print("Error: 'startCommand' section missing in smithery.yaml")
            return False
        
        if config['startCommand']['type'] != 'stdio':
            print("Error: startCommand.type must be 'stdio'")
            return False
        
        if 'configSchema' not in config['startCommand']:
            print("Error: 'configSchema' section missing in smithery.yaml")
            return False
        
        if 'commandFunction' not in config['startCommand']:
            print("Error: 'commandFunction' section missing in smithery.yaml")
            return False
        
        # Check if configSchema is valid JSON Schema
        schema = config['startCommand']['configSchema']
        if not isinstance(schema, dict) or 'type' not in schema:
            print("Error: configSchema must be a valid JSON Schema object")
            return False
        
        # Validate required fields in schema
        if 'properties' not in schema:
            print("Error: configSchema must have a 'properties' section")
            return False
        
        # Check if commandFunction is a string
        if not isinstance(config['startCommand']['commandFunction'], str):
            print("Error: commandFunction must be a string containing JavaScript code")
            return False
        
        print("smithery.yaml validation successful!")
        return True
    
    except yaml.YAMLError as e:
        print(f"Error parsing smithery.yaml: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error validating smithery.yaml: {e}")
        return False


def validate_dockerfile():
    """Validate the Dockerfile exists and has basic requirements."""
    dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
    
    # Check file exists
    if not dockerfile_path.exists():
        print("Error: Dockerfile not found!")
        return False
    
    try:
        # Read Dockerfile content
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        # Check for basic required elements
        checks = {
            "FROM": "FROM" in content,
            "WORKDIR": "WORKDIR" in content,
            "ENTRYPOINT or CMD": "ENTRYPOINT" in content or "CMD" in content
        }
        
        failed_checks = [key for key, passed in checks.items() if not passed]
        
        if failed_checks:
            print(f"Error: Dockerfile is missing required directives: {', '.join(failed_checks)}")
            return False
        
        print("Dockerfile validation successful!")
        return True
    
    except Exception as e:
        print(f"Error validating Dockerfile: {e}")
        return False


def main():
    """Run all validation checks."""
    print("Validating Smithery deployment configuration...")
    
    smithery_valid = validate_smithery_yaml()
    dockerfile_valid = validate_dockerfile()
    
    if smithery_valid and dockerfile_valid:
        print("\nAll validations passed. Configuration is ready for Smithery deployment!")
        return 0
    else:
        print("\nValidation failed. Please fix the issues before deploying to Smithery.")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 