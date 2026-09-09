#!/usr/bin/env python3
"""Wrapper to run build_tier3_supply_network with detailed logging to file."""

import sys
import logging
from pathlib import Path

# Configure logging to file
log_file = Path("build_execution.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

try:
    logger.info("Starting build_tier3_supply_network wrapper...")
    logger.info(f"Working directory: {Path.cwd()}")
    logger.info(f"Python: {sys.executable}")
    logger.info(f"Arguments: {sys.argv}")
    
    # Import and run the actual script
    from src_try.build_tier3_supply_network import main
    
    logger.info("Successfully imported build_tier3_supply_network")
    logger.info("Calling main()...")
    
    main()
    
    logger.info("✓ Script completed successfully")
    
except Exception as e:
    logger.error(f"✗ Script failed: {e}", exc_info=True)
    sys.exit(1)

finally:
    logger.info(f"Log file written to: {log_file.absolute()}")
    print(f"\n✓ Execution log saved to: {log_file}")
