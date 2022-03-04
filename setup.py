#!/usr/bin/env python
from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))
with open(path.join(here, 'requirements.txt')) as f:
    requirements = f.read().splitlines()

setup(
    name='u19_sorting',
    version='0.1.0',
    description='BRAINCoGS scripts to process electrophysiology data',
    author='BRAINCoGS',
    author_email='alvaros@princeton.edu',
    packages=find_packages(exclude=[]),
    install_requires=requirements,
)
