from dataclasses import dataclass
from os import path
from pathlib import Path
from pytest_container.container import Container
from pytest_container.container import DerivedContainer
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import ToParamMixin
from string import Template
from subprocess import check_output
from typing import Dict
from typing import Optional
from typing import Union

from _pytest.config import Config
from py.path import local


@dataclass(frozen=True)
class GitRepositoryBuild(ToParamMixin):
    """Test information storage for running builds using an external git
    repository. It is a required parameter for the `container_git_clone` and
    `host_git_clone` fixtures.
    """

    #: url of the git repository, can end with .git
    repository_url: str = ""
    #: an optional tag at which the repository should be checked out instead of
    #: using the default branch
    repository_tag: Optional[str] = None

    #: The command to run a "build" of the git repository inside a working
    #: copy.
    #: It can be left empty on purpose.
    build_command: str = ""

    def __post_init__(self) -> None:
        if not self.repository_url:
            raise ValueError("A repository url must be provided")

    def __str__(self) -> str:
        return self.repo_name

    @property
    def repo_name(self) -> str:
        """Name of the directory to which the repository will be checked out"""
        repo_without_dot_git = self.repository_url.replace(".git", "")
        repo_without_trailing_slash = (
            repo_without_dot_git[0:-1]
            if repo_without_dot_git[-1] == "/"
            else repo_without_dot_git
        )
        return path.basename(repo_without_trailing_slash)

    @property
    def clone_command(self) -> str:
        """Command to clone the repository at the appropriate tag"""
        clone_cmd_parts = ["git clone --depth 1"]
        if self.repository_tag:
            clone_cmd_parts.append(f"--branch {self.repository_tag}")
        clone_cmd_parts.append(self.repository_url)

        return " ".join(clone_cmd_parts)

    @property
    def test_command(self) -> str:
        """The full test command, including build_command and a cd into the
        correct folder.
        """
        cd_cmd = f"cd {self.repo_name}"
        if self.build_command:
            return f"{cd_cmd} && {self.build_command}"
        return cd_cmd


@dataclass
class MultiStageBuild:
    """Helper class to perform multi-stage container builds using the
    :py:class:`Container` and :py:class:`DerivedContainer` classes.

    This class is essentially just a very simple helper that will replace all
    variables in :py:attr:`containerfile_template` with the correct container
    ids, urls or names from the containers in :py:attr:`containers`.

    For example the following class:

    .. code-block:: python

       MultiStageBuild(
           containers={
               "builder": Container(url="registry.opensuse.org/opensuse/busybox:latest"),
               "runner1": "docker.io/alpine",
           },
           containerfile_template=r'''FROM $builder as builder

       FROM $runner1 as runner1
       ''',
       )

    would yield the following :file:`Containerfile`:

    .. code-block:: Dockerfile

       FROM registry.opensuse.org/opensuse/busybox:latest as builder

       FROM docker.io/alpine as runner1


    The resulting object can either be used to retrieve the rendered
    :file:`Containerfile` or to build the containers:

    .. code-block:: python

       id_of_runner1 = MULTI_STAGE_BUILD.build(
           tmp_path, pytestconfig, container_runtime, "runner1"
       )

    Where ``tmp_path`` and ``pytestconfig`` are the pytest fixtures and
    ``container_runtime`` is an instance of a child class of
    :py:class:`OciRuntimeBase`. For further details, see :py:meth:`build`.

    """

    #: Template string of a :file:`Containerfile` where all containers from
    #: :py:attr:`containers` are inserted when retrieved via
    #: :py:attr:`containerfile`.
    containerfile_template: str

    #: A dictionary mapping the container names used in
    #: :py:attr:`containerfile_template` to :py:class:`Container` or
    #: :py:class:`DerivedContainer` objects or strings.
    containers: Dict[str, Union[Container, DerivedContainer, str]]

    @property
    def containerfile(self) -> str:
        """The rendered :file:`Containerfile` from the template supplied in
        :py:attr:`containerfile_template`.

        """
        return Template(self.containerfile_template).substitute(
            **{k: str(v) for k, v in self.containers.items()}
        )

    def prepare_build(self, tmp_dir: Path, rootdir: local) -> None:
        """Prepares the multistage build: it writes the rendered :file:`Containerfile`
        into ``tmp_dir`` and prepares all containers in :py:attr:`containers` in
        the given ``rootdir``.

        """
        for _, container in self.containers.items():
            if not isinstance(container, str):
                container.prepare_container(rootdir)

        with open(tmp_dir / "Dockerfile", "w") as containerfile:
            containerfile.write(self.containerfile)

    def run_build_step(
        self,
        tmp_dir: Path,
        runtime: OciRuntimeBase,
        target: Optional[str] = None,
    ) -> bytes:
        """Run the multistage build in the given ``tmp_dir`` using the supplied
        ``runtime``. This function requires :py:meth:`prepare_build` to be run
        beforehands.

        Args:
            tmp_dir: the path in which the build was prepared.
            runtime: the container runtime which will be used to perform the build
            target: an optional target to which the build will be run, see `the upstream documentation <https://docs.docker.com/develop/develop-images/multistage-build/#stop-at-a-specific-build-stage>`_ for more information

        Returns:
            Id of the final container that has been built
        """
        return check_output(
            runtime.build_command
            + (["--target", target] if target else [])
            + [str(tmp_dir)]
        )

    def build(
        self,
        tmp_dir: Path,
        rootdir_or_pytestconfig: Union[local, Config],
        runtime: OciRuntimeBase,
        target: Optional[str] = None,
    ) -> str:
        """Perform the complete multistage build to an optional target.

        Args:
            tmp_dir: temporary directory into which the :file:`Containerfile` is
                written and where the build is performed. This value can be
                provided via the `tmp_dir pytest fixture
                <https://docs.pytest.org/en/latest/how-to/tmp_path.html>`_
            rootdir_or_pytestconfig: root directory of the current test suite or
                a `pytestconfig fixture
                <https://docs.pytest.org/en/latest/reference/reference.html?highlight=pytestconfig#std-fixture-pytestconfig>`_
                object. This value is used to prepare the containers in
                :py:attr:`containers`.
            runtime: the container runtime to be used to perform the build. It
                can be retrieved using the
                :py:func:`pytest_container.plugin.container_runtime` fixture.
            target: an optional target to which the build will be run, see `the
                upstream documentation
                <https://docs.docker.com/develop/develop-images/multistage-build/#stop-at-a-specific-build-stage>`_
                for more information. Note that **no** verification of the
                :file:`Containerfile` is performed prior to the
                build. I.e. specifying an invalid target will fail your build.

        Returns:
            Id of the target container or of the last one (when no target was
            supplied) that was build
        """
        self.prepare_build(
            tmp_dir,
            getattr(
                rootdir_or_pytestconfig, "rootdir", rootdir_or_pytestconfig
            ),
        )
        return runtime.get_image_id_from_stdout(
            self.run_build_step(tmp_dir, runtime, target).decode()
        )
