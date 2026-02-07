#!/usr/bin/env python3
"""
Cat Dome - Detection & Tracking System
Main entry point

Usage:
    python main.py [--host HOST] [--port PORT] [--debug]
"""

__version__ = "2.7.8"

import sys
import argparse
import signal

import config
from web.app import run_server, video_processor


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Cat Dome - Detection & Tracking System"
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}'
    )
    parser.add_argument(
        '--host',
        type=str,
        default=config.HOST,
        help=f'Host to bind to (default: {config.HOST})'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=config.PORT,
        help=f'Port to bind to (default: {config.PORT})'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode (not recommended on RPi)'
    )
    parser.add_argument(
        '--mode',
        type=str,
        choices=['cat', 'ball'],
        default=config.DEFAULT_DETECTION_MODE,
        help=f'Initial detection mode (default: {config.DEFAULT_DETECTION_MODE})'
    )
    
    return parser.parse_args()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    print("\n🛑 Shutting down...")
    video_processor.stop()
    sys.exit(0)


def print_banner():
    """Print startup banner"""
    banner = f"""
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║                    🐱 Cat Dome 🏀  v{__version__:<9}                 ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def main():
    """Main entry point"""
    # Parse arguments
    args = parse_args()
    
    # Update config with CLI args
    config.HOST = args.host
    config.PORT = args.port
    config.DEBUG = args.debug
    config.DEFAULT_DETECTION_MODE = args.mode
    
    # Print banner
    print_banner()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"📍 Starting server on http://{args.host}:{args.port}")
    print(f"🎯 Detection mode: {args.mode}")
    print(f"📷 Camera resolution: {config.FRAME_WIDTH}x{config.FRAME_HEIGHT}")
    print(f"⚡ Using {config.TFLITE_NUM_THREADS} threads for inference")
    print("")
    print("Press Ctrl+C to stop")
    print("-" * 50)
    
    try:
        run_server()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    finally:
        video_processor.stop()


if __name__ == '__main__':
    main()
