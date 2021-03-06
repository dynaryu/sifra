.. SIFRA documentation master file, created by
   sphinx-quickstart on Thu Feb 25 09:28:33 2016.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

##############################################################
SIFRA: A Tool for Analysis of Hazard Impacts on Infrastructure
##############################################################

https://github.com/GeoscienceAustralia/sifra |br|
Release: |release|

SIFRA is a **System for Infrastructure Facility Resilience Analysis**.
It comprises a method and software tools that provide a framework
for simulating the fragility of infrastructure facilities to natural
hazards, based on assessment of the fragilities and configuration of
components that comprise the facility. Currently the system is designed
to work with earthquake hazards only. However, in the development of the
methodology and classes, there is a strong emphasis on making the
hazard attribution process and infrastructure models flexible to allow
for expansion to other hazards and new infrastructure sectors.

SIFRA was developed in `Geoscience Australia (GA) <http://www.ga.gov.au/>`_
in support of the agency's vision to contribute to enhancing the resilience
of communities in Australia and its region.


Features
========

- **Open Source:** |br|

  Written in Python, and there is no dependency on
  proprietary tools. It should run on OS X, Windows, and
  Linux platforms. |br|

- **Flexible Facility Model:** |br|

  :term:`Facility` data model is based on graph theory, allowing
  the user to develop arbitrarily complex custom facility models
  for simulation. |br|

- **Extensible Component Library:** |br|

  User can define new instances of `component_type`
  (the building blocks of a facility) and link it to existing or
  custom fragility algorithms. |br|

- **Component Criticality Analysis:** |br|

  Scenario Analysis tools allow users to identify the cost of
  restoration for chosen scenarios, expected restoration times,
  and which component upgrades can most benefit the system.|br|

- **Restoration Prognosis:** |br|

  User can experiment with different levels of hazards and
  post-disaster resource allocation to gauge restoration
  times for facility operations. |br|


Contents
========

.. include:: chapters_for_toc.txt

.. toctree::

    bibliography
    reportglossary

.. include:: copyrightnotice.rst
