from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from config.constants import WORK_DIR_DOCKER, TIMEOUT_DOCKER, DOCKER_IMAGE

def get_docker_executor():
    docker_executor = DockerCommandLineCodeExecutor(
        image=DOCKER_IMAGE,
        work_dir=WORK_DIR_DOCKER,
        timeout=TIMEOUT_DOCKER
    )
    return docker_executor

async def start_docker_executor(docker_executor):
    print("Starting Docker executor...")
    await docker_executor.start()
    print("Docker executor started.")

async def stop_docker_executor(docker_executor):
    print("Stopping Docker executor...")
    await docker_executor.stop()
    print("Docker executor stopped.")