from typing import List, Callable, Union, Tuple

import os
import abc
import copy
import time
import networkx as nx
from .parser import FrofParser
import asyncio
import uuid


class StatusMonitor(abc.ABC):
    """
    Abstract class for status-monitoring capabilities.

    Do not use directly.
    """

    ...

    def emit_status(self):
        """
        Emit a status for the contained FrofPlan.

        Arguments:
            None

        Returns:
            None

        """
        ...


class OneLineStatusMonitor(StatusMonitor):
    """
    A status monitor that keeps itself constrainted to a single line.

    Good for running in a CLI.
    During a run, prints:

        🤔 7 jobs running, 9 remaining.

    While the run boots, prints:

        Starting job with 17 jobs total.

    When a run has no more remaining jobs, prints:

        👌 0 jobs running, 0 remaining.

    """

    def __init__(self, fe: "FrofExecutor") -> None:
        """
        Create a new OneLineStatusMonitor.



        Arguments:
            fe (FrofExecutor): The Executor to print for during runs

        Returns:
            None

        """
        self.fe = fe

    def emit_status(self):
        """
        Emit the current status of self.fe.

        Prints directly to stdout. Uses emojis. This is not the most backward-
        compatible of all systems.

        Arguments:
            None

        Returns:
            None

        """
        next_job_count = len(self.fe.get_next_jobs())
        if next_job_count:
            emoji = "🤔"
        else:
            emoji = "👌"
        remaining = len(self.fe.get_current_network())
        print(
            f"{emoji}\t {next_job_count} jobs running, {remaining} remaining.", end="\r"
        )

    def launch_status(self):
        """
        Print the current status pre-run of the Plan.

        Arguments:
            None

        Returns:
            None

        """
        print(f"Starting job with {len(self.fe.get_network())} jobs total.", end="\r")


class FrofPlan:
    """
    FrofPlan objects hold a network of jobs to run, and manage the execution.

    You can invoke this with:

        FrofPlan(FROF_FILE_NAME)

        FrofPlan(FROF_FILE_CONTENTS)

        FrofPlan(my_DiGraph)

    """

    def __init__(self, frof):
        """
        Create a new FrofPlan.

        Arguments:
            frof (Union[str, nx.DiGraph]): The job network to run. Can be a
                network, designed manually, or a string representation of a
                plan, OR the name of a file to read for the plan.

        Returns:
            None

        """
        self.plan_id = str(uuid.uuid4())
        if isinstance(frof, str):
            if "\n" not in frof:
                try:
                    with open(os.path.expanduser(frof), "r") as fh:
                        self.network = FrofParser().parse(fh.read())
                except FileNotFoundError:
                    self.network = FrofParser().parse(frof)
        else:
            self.network = frof

    def as_networkx(self):
        """
        Return this Plan as a NetworkX graph.

        Arguments:
            None

        Returns:
            nx.DiGraph: This plan network

        """
        return copy.deepcopy(self.network)


class FrofExecutor(abc.ABC):
    """
    FrofExecutors are responsible for converting a Plan to actual runtime.

    There might be, for example, a LocalFrofExecutor, a ClusterFrofExecutor...
    This is the abstract base class; do not use this class directly.
    """

    ...

    def get_next_jobs(self) -> List:
        ...

    def get_current_network(self) -> nx.DiGraph:
        ...

    def get_network(self) -> nx.DiGraph:
        ...


class LocalFrofExecutor(FrofExecutor):
    """
    A FrofExecutor that runs tasks locally in the current bash shell.

    This is useful for get-it-done ease of use, but may not be the most
    powerful way to schedule tasks...
    """

    def __init__(
        self, fp: "FrofPlan", status_monitor: Callable = OneLineStatusMonitor
    ) -> None:
        """
        Create a new LocalFrofExecutor.

        Arguments:
            fp (FrofPlan): The FrofPlan to execute. Should already be populated
                with a FrofPlan#network attribute.
            status_monitor (StatusMonitor): Constructor for the StatusMonitor
                to use to track progress in this execution.

        """
        self.fp = fp
        self.status_monitor = status_monitor(self)
        self.current_network = nx.DiGraph()

    def get_current_network(self) -> nx.DiGraph:
        """
        Get a pointer to the current_network of this execution.

        Arguments:
            None

        Returns:
            nx.DiGraph: The current (mutable) network of this execution

        """
        return self.current_network

    def get_network(self) -> nx.DiGraph:
        """
        Get a pointer to the unchanged, original network plan.

        Arguments:
            None

        Returns:
            nx.DiGraph: The (mutable) network plan for this execution

        """
        return self.fp.network

    def get_next_jobs(self) -> List:
        """
        Get a list of the next jobs to run.

        Arguments:
            None

        Returns:
            Tuple[str, FrofJob]: (Job Name, Job Object)

        """
        return [
            (i, j["job"])
            for i, j in self.current_network.nodes(data=True)
            if self.current_network.in_degree(i) == 0
        ]

    def execute(self) -> None:
        """
        Execute the FrofPlan locally, using the current shell.

        Arguments:
            None

        Returns:
            None

        """
        run_id = str(uuid.uuid4())
        self.current_network = copy.deepcopy(self.fp.network)
        self.status_monitor.launch_status()
        while len(self.current_network):
            current_jobs = self.get_next_jobs()
            loop = asyncio.get_event_loop()
            jobs = asyncio.gather(
                *[
                    job.run(
                        env_vars={
                            "FROF_BATCH_ITER": str(itercounter),
                            "FROF_JOB_NAME": str(i),
                            "FROF_RUN_ID": run_id,
                            "FROF_PLAN_ID": self.fp.plan_id,
                        }
                    )
                    for itercounter, (i, job) in enumerate(current_jobs)
                ]
            )
            _ = loop.run_until_complete(jobs)
            for (i, _) in current_jobs:
                self.current_network.remove_node(i)
            self.status_monitor.emit_status()
