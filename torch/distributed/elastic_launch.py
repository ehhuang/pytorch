#!/usr/bin/env python3

# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

r"""
This module provides similar functionality as ``torch.distributed.launch``,
with the following additional functionalities:

1. Worker failures are handled gracefully by restarting all workers.

2. Worker ``RANK`` and ``WORLD_SIZE`` are assigned automatically.

3. Number of nodes is allowed to change between min and max sizes (elasticity).

**Usage:**

1. Single-node multi-worker (with sidecar etcd server)

::

    >>> python -m torch.distributed.elastic_launch
        --standalone
        --nnodes=1
        --nproc_per_node=$NUM_TRAINERS
        YOUR_TRAINING_SCRIPT.py (--arg1 ... train script args...)

2. Fault tolerant (fixed sized number of workers, no elasticity).:

::

    >>> python -m torch.distributed.elastic_launch
        --nnodes=$NUM_NODES
        --nproc_per_node=$NUM_TRAINERS
        --rdzv_id=$JOB_ID
        --rdzv_backend=etcd
        --rdzv_endpoint=$ETCD_HOST:$ETCD_PORT
        YOUR_TRAINING_SCRIPT.py (--arg1 ... train script args...)

3. Elastic (``min=1``, ``max=4``):

::

    >>> python -m torch.distributed.elastic_launch
        --nnodes=1:4
        --nproc_per_node=$NUM_TRAINERS
        --rdzv_id=$JOB_ID
        --rdzv_backend=etcd
        --rdzv_endpoint=$ETCD_HOST:$ETCD_PORT
        YOUR_TRAINING_SCRIPT.py (--arg1 ... train script args...)

**Note on rendezvous backend**:

For multi-node training you need to specify:

1. ``--rdzv_id``: a unique job id (shared by all nodes participating in the job)
2. ``--rdzv_backend``: an implementation of ``torch.distributed.elastic.rendevous.RendezvousHandler``
3. ``--rdzv_endpoint``: ``host:port``-style endpoint where the rdzv backend is running.

Currently only ``etcd`` rdzv backend is supported out of the box.
To use ``etcd``, setup an etcd server with the ``v2`` api enabled
(e.g. ``--enable-v2``).

.. warning:: ``EtcdRendezvous`` uses etcd api v2. You MUST enable the v2
             api on the etcd server. Our tests use etcd v3.4.3.

**Definitions:**

1. ``Node`` - Physical instance or container.
    Maps to the unit that the job manager works with.

2. ``Worker`` - A worker in the context of distributed training.

3. ``Worker Group`` - Workers that execute the same function (e.g. trainers)

4. ``Local Worker Group`` - Subset of the workers in the
    worker group running on the same Node

5. ``RANK`` - rank of the worker within a worker group.

6. ``WORLD_SIZE`` - total number of workers in a worker group.

7. ``LOCAL_RANK`` - rank of the worker within a local worker group

8. ``LOCAL_WORLD_SIZE`` - size of the local worker group

9. ``rdzv_id`` - user defined id that uniquely identifies the worker group
      for a job. This id is used by each node to join as a member of a particular
      worker group.

9. ``rdzv_backend`` - the backend store of rendezvous (e.g. etcd). This is
    typically a strongly consistent key-value store.

10. ``rdzv_endpoint`` - rdzv backend server endpoint in ``host:port`` format.

A ``Node`` runs ``LOCAL_WORLD_SIZE`` workers which comprise a ``LocalWorkerGroup``.
The union of all ``LocalWorkerGroups`` in the nodes in the job comprise the
``WorkerGroup``.

**Environment Variables:**

The following environment variables are made available to you in your
script:

1. ``LOCAL_RANK`` -  local rank

2. ``RANK`` -  global rank

3. ``GROUP_RANK`` - rank of the worker group. A number between 0 - ``max_nnodes``.
        When running a single worker group per node, this is the rank of the node.

4. ``ROLE_RANK`` -  the rank of the worker across all the workers tha have the same
        role. The role of the worker is specified in the ``WorkerSpec``.

5. ``LOCAL_WORLD_SIZE`` - local world size (e.g. number of workers running locally).
       Equal to ``--nproc_per_node`` specified on ``torch.distributed.elastic_launch``.

6. ``WORLD_SIZE`` - world size (total number of workers in the job).

7. ``ROLE_WORLD_SIZE`` - the total number of workers that was launched with the same
        role specified in ``WorkerSpec``.

8. ``MASTER_ADDR`` - fqdn of the host that is running worker with rank 0.
   Used to initialize torch distributed backend.

9. ``MASTER_PORT`` - port on the ``MASTER_ADDR`` that can be used to
   host the tcp ``c10d`` store.

10. ``TORCHELASTIC_RESTART_COUNT`` - number of worker group restarts so far.

11. ``TORCHELASTIC_MAX_RESTARTS`` - configured max number of restarts.

12. ``TORCHELASTIC_RUN_ID`` - equal to rdzv run_id (e.g. unique job id).

**Deployment:**

1. Start the rdzv backend server and get the endpoint
   (to be passed as ``--rdzv_endpoint`` to the launcher script)

2. Single-node multi-worker - start the launcher on the host to start
   the agent process which creates and monitors a local worker group.

3. Multi-node multi-worker - Start the launcher with the same arguments
   on all the nodes participating in training.

When using a job/cluster manager the entry point command to the multi-node
job is invoking this launcher.

**Failure Modes:**

1. Worker failure - For a training job with ``n`` workers, if ``k <= n`` workers fail
   all workers are stopped and restarted up to ``max_restarts``.

2. Agent failure - An agent failure results in local worker group failure,
   it is up to the job manager to fail the entire job (gang semantics) or attempt
   to replace the node. Both behaviors are supported by the agent.

3. Node failure - Same as agent failure.

**Membership Changes:**

1. Node departure (scale-down) - agent is notified of the departure,
   all existing workers are stopped, a new ``Worker Group`` is formed and all
   workers are started with a new ``RANK`` and ``WORLD_SIZE``.

2. Node arrival (scale-up) - the new node is admitted to the job,
   all existing workers are stopped, a new ``Worker Group`` is formed and all
   workers are started with a new ``RANK`` and ``WORLD_SIZE``.


**Important Notices:**

1. All the items in the important notices section of ``torch.distributed.launch``
   apply to this module as well

2. The environment variables necessary to initialize a torch process group
   are provided to you by this module, no need for you to pass ``RANK`` manually.
   To initialize a process group in your training script, simply run

::

 >>> import torch.distributed as dist
 >>> dist.init_process_group(backend="gloo|nccl")

3. On failures or membership changes ALL surviving workers are killed
   immediately. Make sure to checkpoint your progress. The frequency of
   checkpoints should depend on your job's tolerance for lost work.

4. This module only supports homogeneous ``LOCAL_WORLD_SIZE``. That is,
   it is assumed that all nodes run the same number of local workers (per role).

5. ``RANK`` is NOT stable. Between restarts, the local workers on a node
   can be assgined a different range of ranks than before. NEVER hard code
   any assumptions about the stable-ness of ranks or some correlation between
   ``RANK`` and ``LOCAL_RANK``.

6. When using elasticity (``min_size != max_size``) DO NOT hard code
   assumptions about ``WORLD_SIZE`` as the world size can change as
   nodes are allowed to leave and join.

7. It is recommended your script have the following structure

::

  def main():
    load_checkpoint(checkpoint_path)
    initialize()
    train()

  def train():
    for batch in iter(dataset):
      train_step(batch)

      if should_checkpoint:
        save_checkpoint(checkpoint_path)
"""
import logging
import os
import sys
import uuid
from argparse import REMAINDER, ArgumentParser
from typing import List, Tuple

import torch
from torch.distributed.argparse_util import check_env, env
from torch.distributed.elastic.multiprocessing import Std
from torch.distributed.elastic.rendezvous.etcd_server import EtcdServer
from torch.distributed.elastic.rendezvous.utils import _parse_rendezvous_config
from torch.distributed.elastic.utils import macros
from torch.distributed.elastic.utils.logging import get_logger
from torch.distributed.launcher.api import LaunchConfig, elastic_launch


log = get_logger()


def get_args_parser() -> ArgumentParser:
    """
    Helper function parsing the command line options.
    """

    parser = ArgumentParser(description="torchelastic elastic training launcher")

    # Arguments for the launch helper
    # worker/node size related arguments
    parser.add_argument(
        "--nnodes",
        action=env,
        type=str,
        default="1:1",
        help="number of nodes or MIN_NODES:MAX_NODES",
    )
    parser.add_argument(
        "--nproc_per_node",
        action=env,
        type=str,
        default="auto",
        help="number of workers per node, supported values: [auto, cpu, gpu, int]",
    )

    # rendezvous related arguments
    parser.add_argument(
        "--rdzv_backend",
        action=env,
        type=str,
        default="static",
        help="rendezvous backend",
    )
    parser.add_argument(
        "--rdzv_endpoint",
        action=env,
        type=str,
        default="",
        help="rendezvous backend server host:port",
    )
    parser.add_argument(
        "--rdzv_id",
        action=env,
        default="none",
        type=str,
        help="user defined group id",
    )
    parser.add_argument(
        "--rdzv_conf",
        action=env,
        type=str,
        default="",
        help="additional rdzv configuration (conf1=v1,conf2=v2,...)",
    )

    # sidecar embed rdzv backend that defaults to etcd
    parser.add_argument(
        "--standalone",
        action=check_env,
        help="starts a local, standalone rdzv backend that is represented by"
        " etcd server on a random free port"
        "using the etcd binary specified in TORCHELASTIC_ETCD_BINARY_PATH"
        " env var or the one found in PATH."
        " Useful when launching single-node, multi-worker job."
        " If specified --rdzv_backend, --rdzv_endpoint, --rdzv_id"
        " are autoassigned, any explicitly set values are ignored",
    )

    # user-code launch related arguments
    parser.add_argument(
        "--max_restarts",
        action=env,
        type=int,
        default=3,
        help="max number of worker group restarts before failing",
    )
    parser.add_argument(
        "--monitor_interval",
        action=env,
        type=float,
        default=5,
        help="interval (in seconds) to monitor the state of workers",
    )
    parser.add_argument(
        "--start_method",
        action=env,
        type=str,
        default="spawn",
        choices=["spawn", "fork", "forkserver"],
        help="multiprocessing start_method to use when creating workers",
    )
    parser.add_argument(
        "--role",
        action=env,
        type=str,
        default="default",
        help="user-defined role for the workers",
    )
    parser.add_argument(
        "-m",
        "--module",
        action=check_env,
        help="Changes each process to interpret the launch script "
        "as a python module, executing with the same behavior as"
        "'python -m'.",
    )
    parser.add_argument(
        "--no_python",
        action=check_env,
        help='Do not prepend the training script with "python" - just exec '
        "it directly. Useful when the script is not a Python script.",
    )

    parser.add_argument(
        "--log_dir",
        action=env,
        type=str,
        default=None,
        help="base dir to use for log files (e.g. /var/log/torchelastic)"
        " can reuse the same dir for multiple runs "
        "(a unique job-level subdir is created with rdzv_id as the prefix)",
    )

    parser.add_argument(
        "-r",
        "--redirects",
        action=env,
        type=str,
        default="0",
        help="std streams to redirect into a log file in the log_dir"
        " (e.g. [-r 3] redirects both stdout+stderr for all workers,"
        " [-r 0:1,1:2] redirects stdout for local rank 0 and stderr for local rank 1)",
    )

    parser.add_argument(
        "-t",
        "--tee",
        action=env,
        type=str,
        default="0",
        help="tee std streams into a log file and also to console (see --redirects for format)",
    )

    # backwards compatible params with caffe2.distributed.launch

    parser.add_argument(
        "--node_rank",
        type=int,
        action=env,
        default=0,
        help="The rank of the node for multi-node distributed " "training",
    )

    parser.add_argument(
        "--master_addr",
        default="127.0.0.1",
        type=str,
        action=env,
        help="Master node (rank 0)'s address, should be either "
        "the IP address or the hostname of node 0, for "
        "single node multi-proc training, the "
        "--master_addr can simply be 127.0.0.1"
        "IPV6 should have the following pattern: `[0:0:0:0:0:0:0:1]`",
    )
    parser.add_argument(
        "--master_port",
        default=29500,
        type=int,
        action=env,
        help="Master node (rank 0)'s free port that needs to "
        "be used for communication during distributed "
        "training",
    )

    # positional
    parser.add_argument(
        "training_script",
        type=str,
        help="The full path to the single GPU training "
        "program/script to be launched in parallel, "
        "followed by all the arguments for the "
        "training script",
    )

    # rest from the training program
    parser.add_argument("training_script_args", nargs=REMAINDER)
    return parser
    # return parser.parse_args(args)


def parse_args(args):
    parser = get_args_parser()
    parser.add_argument(
        "--use_env",
        default=True,
        action="store_true",
        help="Use environment variable to pass "
        "'local rank'. For legacy reasons, the default value is False. "
        "If set to True, the script will not pass "
        "--local_rank as argument, and will instead set LOCAL_RANK.",
    )
    return parser.parse_args(args)


def parse_min_max_nnodes(nnodes: str):
    arr = nnodes.split(":")

    if len(arr) == 1:
        min_nodes = max_nodes = int(arr[0])
    elif len(arr) == 2:
        min_nodes = int(arr[0])
        max_nodes = int(arr[1])
    else:
        raise RuntimeError(f'nnodes={nnodes} is not in "MIN:MAX" format')

    return min_nodes, max_nodes


def determine_local_world_size(nproc_per_node: str):
    try:
        logging.info(f"Using nproc_per_node={nproc_per_node}.")
        return int(nproc_per_node)
    except ValueError:
        if nproc_per_node == "cpu":
            num_proc = os.cpu_count()
            device_type = "cpu"
        elif nproc_per_node == "gpu":
            if not torch.cuda.is_available():
                raise ValueError("Cuda is not available.")
            device_type = "gpu"
            num_proc = torch.cuda.device_count()
        elif nproc_per_node == "auto":
            if torch.cuda.is_available():
                num_proc = torch.cuda.device_count()
                device_type = "gpu"
            else:
                num_proc = os.cpu_count()
                device_type = "cpu"
        else:
            raise ValueError(f"Unsupported nproc_per_node value: {nproc_per_node}")

        log.info(
            f"Using nproc_per_node={nproc_per_node},"
            f" seting to {num_proc} since the instance "
            f"has {os.cpu_count()} {device_type}"
        )
        return num_proc


def get_rdzv_endpoint(args):
    if args.rdzv_backend == "static":
        return f"{args.master_addr}:{args.master_port}"
    else:
        return args.rdzv_endpoint


def config_from_args(args) -> Tuple[LaunchConfig, List[str]]:
    # If ``args`` not passed, defaults to ``sys.argv[:1]``
    min_nodes, max_nodes = parse_min_max_nnodes(args.nnodes)
    assert 0 < min_nodes <= max_nodes
    assert args.max_restarts >= 0

    nproc_per_node = determine_local_world_size(args.nproc_per_node)
    if "OMP_NUM_THREADS" not in os.environ and nproc_per_node > 1:
        omp_num_threads = 1
        print(
            f"*****************************************\n"
            f"Setting OMP_NUM_THREADS environment variable for each process to be "
            f"{omp_num_threads} in default, to avoid your system being overloaded, "
            f"please further tune the variable for optimal performance in "
            f"your application as needed. \n"
            f"*****************************************"
        )
        # This env variable will be passed down to the subprocesses
        os.environ["OMP_NUM_THREADS"] = str(omp_num_threads)

    rdzv_configs = _parse_rendezvous_config(args.rdzv_conf)

    if args.rdzv_backend == "static":
        rdzv_configs["rank"] = args.node_rank

    rdzv_endpoint = get_rdzv_endpoint(args)

    config = LaunchConfig(
        min_nodes=min_nodes,
        max_nodes=max_nodes,
        nproc_per_node=nproc_per_node,
        run_id=args.rdzv_id,
        role=args.role,
        rdzv_endpoint=rdzv_endpoint,
        rdzv_backend=args.rdzv_backend,
        rdzv_configs=rdzv_configs,
        max_restarts=args.max_restarts,
        monitor_interval=args.monitor_interval,
        start_method=args.start_method,
        redirects=Std.from_str(args.redirects),
        tee=Std.from_str(args.tee),
    )

    with_python = not args.no_python
    cmd = []
    if with_python:
        cmd = [sys.executable, "-u"]
        if args.module:
            cmd.append("-m")
    else:
        if not args.use_env:
            raise ValueError(
                "When using the '--no_python' flag,"
                " you must also set the '--use_env' flag."
            )
        if args.module:
            raise ValueError(
                "Don't use both the '--no_python' flag"
                " and the '--module' flag at the same time."
            )
    cmd.append(args.training_script)
    if not args.use_env:
        log.warning(
            "`torch.distributed.launch` is Deprecated. Use torch.distributed.elastic_launch"
        )
        cmd.append(f"--local_rank={macros.local_rank}")
    cmd.extend(args.training_script_args)

    return config, cmd


def run(args):
    if args.standalone:
        etcd_server = EtcdServer()
        etcd_server.start()
        args.rdzv_backend = "etcd"
        args.rdzv_endpoint = etcd_server.get_endpoint()
        args.rdzv_id = str(uuid.uuid4())
        log.info(
            f"\n**************************************\n"
            f"Rendezvous info:\n"
            f"--rdzv_backend={args.rdzv_backend} "
            f"--rdzv_endpoint={args.rdzv_endpoint} "
            f"--rdzv_id={args.rdzv_id}\n"
            f"**************************************\n"
        )

    config, cmd = config_from_args(args)

    try:
        elastic_launch(
            config=config,
            entrypoint=cmd[0],
        )(*cmd[1:])
    finally:
        if args.standalone:
            etcd_server.stop()


def main(args=None):
    args = parse_args(args)
    run(args)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(asctime)s %(module)s: %(message)s"
    )
    log.info(f"Running torch.distributed.elastic_launch with args: {sys.argv}")
    main()
