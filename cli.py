import argparse

def orienter_ui():
    parser = argparse.ArgumentParser(description='Command-line interface for the Orienter UI')
    # Add command-line arguments here
    parser.add_argument('--option', type=str, help='An example option')
    args = parser.parse_args()
    
    # Call the actual function with the parsed arguments
    print(f'Option selected: {args.option}')

if __name__ == '__main__':
    orienter_ui()