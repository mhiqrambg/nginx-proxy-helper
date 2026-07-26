"""Backward compatibility setup.py for editable install with older pip."""
from setuptools import setup, find_packages

setup(
    name="nginx-proxy-helper",
    version="1.0.0",
    packages=find_packages(),
    include_package_data=True,
    package_data={"nginx_proxy_helper": ["templates/*.j2"]},
    install_requires=[
        "click>=8.0",
        "Jinja2>=3.0",
        "dnspython>=2.3",
        "tabulate>=0.9",
        "rich>=13.0",
    ],
    entry_points={
        "console_scripts": [
            "proxy=nginx_proxy_helper.cli:cli",
        ],
    },
)
