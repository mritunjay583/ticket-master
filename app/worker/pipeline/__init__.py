"""Ticket-processing pipeline steps (deterministic simulations).

Each step is a small, pure function so it is trivial to unit-test in isolation. A real
implementation (ML model, LLM, rules engine) could replace any step without changing the worker.
"""
