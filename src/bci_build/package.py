#!/usr/bin/env python3
from __future__ import annotations

import abc
import asyncio
import datetime
from dataclasses import dataclass, field
from itertools import product
import enum
import os
from typing import Callable, ClassVar, Dict, List, Literal, Optional, Union

import aiofiles

from bci_build.data import SUPPORTED_SLE_SERVICE_PACKS
from bci_build.templates import DOCKERFILE_TEMPLATE, KIWI_TEMPLATE, SERVICE_TEMPLATE


@enum.unique
class ReleaseStage(enum.Enum):
    """Values for the ``release-stage`` label of a BCI"""

    BETA = "beta"
    RELEASED = "released"

    def __str__(self) -> str:
        return self.value


@enum.unique
class ImageType(enum.Enum):
    """Values of the ``image-type`` label of a BCI"""

    SLE_BCI = "sle-bci"
    APPLICATION = "application"

    def __str__(self) -> str:
        return self.value


@enum.unique
class BuildType(enum.Enum):
    """Options for how the image is build, either as a kiwi build or from a
    :file:`Dockerfile`.

    """

    DOCKER = "docker"
    KIWI = "kiwi"

    def __str__(self) -> str:
        return self.value


@enum.unique
class PackageType(enum.Enum):
    """Package types that are supported by kiwi, see
    `<https://osinside.github.io/kiwi/concept_and_workflow/packages.html>`_ for
    further details.

    Note that these are only supported for kiwi builds.

    """

    DELETE = "delete"
    UNINSTALL = "uninstall"
    BOOTSTRAP = "bootstrap"
    IMAGE = "image"

    def __str__(self) -> str:
        return self.value


@dataclass
class Package:
    """Representation of a package in a kiwi build, for Dockerfile based builds the
    :py:attr:`~Package.pkg_type`.

    """

    #: The name of the package
    name: str

    #: The package type. This parameter is only applicable for kiwi builds and
    #: defines into which ``<packages>`` element this package is inserted.
    pkg_type: PackageType = PackageType.IMAGE

    def __str__(self) -> str:
        return self.name


@dataclass
class Replacement:
    """Represents a replacement via the `obs-service-replace_using_package_version
    <https://github.com/openSUSE/obs-service-replace_using_package_version>`_.

    """

    #: regex to be replaced in the Dockerfile
    regex_in_dockerfile: str

    #: package name to be queried for the version
    package_name: str

    #: specify how the version should be formated, see
    #: `<https://github.com/openSUSE/obs-service-replace_using_package_version#usage>`_
    #: for further details
    parse_version: Optional[
        Literal["major", "minor", "patch", "patch_update", "offset"]
    ] = None


@dataclass
class BaseContainerImage(abc.ABC):
    """Base class for all Base Container Images."""

    #: Name of this image. It is used to generate the build tags, i.e. it
    #: defines under which name this image is published.
    name: str

    #: Human readable name that will be inserted into the image title and description
    pretty_name: str

    #: The name of the package on IBS in ``SUSE:SLE-15-SP$ver:Update:BCI``
    ibs_package: str

    #: The SLE service pack to which this package belongs
    sp_version: SUPPORTED_SLE_SERVICE_PACKS

    #: This container images release stage
    release_stage: ReleaseStage

    #: The container from which this one is derived. defaults to
    #: ``suse/sle15:15.$SP`` when an empty string is used.
    #: When from image is ``None``, then this image will not be based on
    #: **anything**, i.e. the ``FROM`` line is missing in the ``Dockerfile``.
    from_image: Optional[str] = ""

    is_latest: bool = False

    #: An optional entrypoint for the image, it is omitted if empty or ``None``
    entrypoint: Optional[str] = None

    #: Extra environment variables to be set in the container
    env: Union[Dict[str, Union[str, int]], Dict[str, str], Dict[str, int]] = field(
        default_factory=dict
    )

    #: Add any replacements via `obs-service-replace_using_package_version
    #: <https://github.com/openSUSE/obs-service-replace_using_package_version>`_
    #: that are used in this image into this list.
    #: See also :py:class:`~Replacement`
    replacements_via_service: List[Replacement] = field(default_factory=list)

    #: If true, then the label ``com.suse.techpreview`` is set to
    #: ``"true"``. The label is omitted if this property is false.
    tech_preview: bool = True

    #: Additional labels that should be added to the image. These are added into
    #: the ``PREFIXEDLABEL`` section.
    extra_labels: Dict[str, str] = field(default_factory=dict)

    #: Packages to be installed inside the container image
    package_list: Union[List[str], List[Package]] = field(default_factory=list)

    #: This string is appended to the automatically generated dockerfile and can
    #: contain arbitrary instructions valid for a :file:`Dockerfile`.
    #: **Caution** Setting both this property and
    #: :py:attr:`~BaseContainerImage.config_sh_script` is not possible and will
    #: result in an error.
    custom_end: str = ""

    #: A bash script that is put into :file:`config.sh` if a kiwi image is
    #: created. If a :file:`Dockerfile` based build is used then this script is
    #: prependend with a ``RUN`` and added at the end of the ``Dockerfile``. It
    #: must thus fit on a single line if you want to be able to build from a
    #: kiwi and :file:`Dockerfile` at the same time!
    config_sh_script: str = ""

    #: The maintainer of this image, defaults to SUSE
    maintainer: str = "SUSE LLC (https://www.suse.com/)"

    #: Additional files that belong into this container-package.
    #: The key is the filename, the values are the file contents.
    extra_files: Dict[str, Union[str, bytes]] = field(default_factory=dict)

    #: Additional names under which this image should be published alongside
    #: :py:attr:`~BaseContainerImage.name`.
    #: These names are only inserted into the
    #: :py:attr:`~BaseContainerImage.build_tags`
    additional_names: List[str] = field(default_factory=list)

    #: By default the containers get the labelprefix
    #: ``com.suse.bci.{self.name}``. If this value is not an empty string, then
    #: it is used instead of the name after ``com.suse.bci.``.
    custom_labelprefix_end: str = ""

    #: Provide a custom description instead of the automatically generated one
    custom_description: str = ""

    #: Define whether this container image is built using docker or kiwi
    build_recipe_type: BuildType = BuildType.DOCKER

    #: The default url that is put into the ``org.opencontainers.image.url``
    #: label
    URL: ClassVar[str] = "https://www.suse.com/products/server/"

    #: The vendor that is put into the ``org.opencontainers.image.vendor``
    #: label
    VENDOR: ClassVar[str] = "SUSE LLC"

    def __post_init__(self) -> None:
        if not self.package_list:
            raise ValueError(f"No packages were added to {self.pretty_name}.")
        if self.config_sh_script and self.custom_end:
            raise ValueError(
                "Cannot specify both a custom_end and a config.sh script! Use just config_sh_script."
            )

    @property
    @abc.abstractmethod
    def nvr(self) -> str:
        """Name-version identifier used to uniquely identify this image."""
        pass

    @property
    @abc.abstractmethod
    def version_label(self) -> str:
        """The "main" version label of this image.

        It is added as the ``org.opencontainers.image.version`` label to the
        container image and also added to the
        :py:attr:`~BaseContainerImage.build_tags`.

        """
        pass

    @property
    def ibs_project(self) -> str:
        """The project on IBS where this Container Image is maintained."""
        return f"SUSE:SLE-15-SP{self.sp_version}:Update:BCI"

    @property
    def dockerfile_custom_end(self) -> str:
        """This part is appended at the end of the :file:`Dockerfile`. It is either
        generated from :py:attr:`BaseContainerImage.custom_end` or by prepending
        ``RUN`` in front of :py:attr:`BaseContainerImage.config_sh_script`. The
        later implies that the script in that variable fits on a single line or
        newlines are escaped, e.g. via `ansi escapes
        <https://stackoverflow.com/a/33439625>`_.

        """
        if self.custom_end:
            return self.custom_end
        if self.config_sh_script:
            return f"RUN {self.config_sh_script}"
        return ""

    @property
    def config_sh(self) -> str:
        """The full :file:`config.sh` script required for kiwi builds."""
        if not self.config_sh_script:
            if self.custom_end:
                raise ValueError(
                    "This image cannot be build as a kiwi image, it has a `custom_end` set."
                )
            return ""
        return f"""#!/bin/bash -e

# Copyright (c) {datetime.datetime.now().date().strftime("%Y")} SUSE LLC, Nuernberg, Germany.
#
# All modifications and additions to the file contributed by third parties
# remain the property of their copyright owners, unless otherwise agreed
# upon. The license for this file, and modifications and additions to the
# file, is the same license as for the pristine package itself (unless the
# license for the pristine package is not an Open Source License, in which
# case the license is the MIT License). An "Open Source License" is a
# license that conforms to the Open Source Definition (Version 1.9)
# published by the Open Source Initiative.

test -f /.kconfig && . /.kconfig
test -f /.profile && . /.profile

echo "Configure image: [$kiwi_iname]..."

#======================================
# Setup baseproduct link
#--------------------------------------
if [ ! -e /etc/products.d/baseproduct ]; then
    suseSetupProduct
fi

#======================================
# Import repositories' keys
#--------------------------------------
suseImportBuildKey

{self.config_sh_script}

exit 0
"""

    @property
    def packages(self) -> str:
        """The list of packages joined so that it can be appended to a
        :command:`zypper in`.

        """
        for pkg in self.package_list:
            if isinstance(pkg, Package) and pkg.pkg_type != PackageType.IMAGE:
                raise ValueError(
                    f"Cannot add a package of type {pkg.pkg_type} into a Dockerfile based build."
                )
        return " ".join(str(pkg) for pkg in self.package_list)

    @property
    def kiwi_packages(self) -> str:
        """The package list as xml elements that are inserted into a kiwi build
        description file.

        """

        def create_pkg_filter_func(
            pkg_type: PackageType,
        ) -> Callable[[Union[str, Package]], bool]:
            def pkg_filter_func(p: Union[str, Package]) -> bool:
                if isinstance(p, str):
                    return pkg_type == PackageType.IMAGE
                return p.pkg_type == pkg_type

            return pkg_filter_func

        PKG_TYPES = (
            PackageType.DELETE,
            PackageType.BOOTSTRAP,
            PackageType.IMAGE,
            PackageType.UNINSTALL,
        )
        delete_packages, bootstrap_packages, image_packages, uninstall_packages = (
            list(filter(create_pkg_filter_func(pkg_type), self.package_list))
            for pkg_type in PKG_TYPES
        )

        res = ""
        for (pkg_list, pkg_type) in zip(
            (delete_packages, bootstrap_packages, image_packages, uninstall_packages),
            PKG_TYPES,
        ):
            if len(pkg_list) > 0:
                res += (
                    f"""  <packages type="{pkg_type}">
    """
                    + """
    """.join(
                        f'<package name="{pkg}"/>' for pkg in pkg_list
                    )
                    + """
  </packages>
"""
                )
        return res

    @property
    def env_lines(self) -> str:
        """Part of the :file:`Dockerfile` that sets every environment variable defined
        in :py:attr:`~BaseContainerImage.env`.

        """
        return "\n".join(f'ENV {k}="{v}"' for k, v in self.env.items())

    @property
    def kiwi_env_entry(self) -> str:
        """Environment variable settings for a kiwi build recipe."""
        if not self.env:
            return ""
        return (
            """        <environment>
          """
            + """
          """.join(
                f'<env name="{k}" value="{v}"/>' for k, v in self.env.items()
            )
            + """
        </environment>
"""
        )

    @property
    @abc.abstractmethod
    def image_type(self) -> ImageType:
        """Define the value of the ``com.suse.image-type`` label."""
        pass

    @property
    @abc.abstractmethod
    def build_tags(self) -> List[str]:
        """All build tags that will be added to this image. Note that build tags are
        full paths on the registry and not just a tag.

        """
        pass

    @property
    def reference(self) -> str:
        """The primary URL via which this image can be pulled. It is used to set the
        ``org.opensuse.reference`` label and defaults to
        ``registry.suse.com/{self.build_tags[0]}``.

        """
        return f"registry.suse.com/{self.build_tags[0]}"

    @property
    def description(self) -> str:
        """The description of this image which is inserted into the
        ``org.opencontainers.image.description`` label.

        If :py:attr:`BaseContainerImage.custom_description` is set, then that
        value is used. Otherwise it reuses
        :py:attr:`BaseContainerImage.pretty_name` to generate a description.

        """
        return (
            self.custom_description
            or f"Image containing {self.pretty_name} based on the SLE Base Container Image."
        )

    @property
    def title(self) -> str:
        """The image title that is inserted into the ``org.opencontainers.image.title``
        label.

        It is generated from :py:attr:`BaseContainerImage.pretty_name` as
        follows: ``"SLE BCI {self.pretty_name} Container Image"``.

        """
        return f"SLE BCI {self.pretty_name} Container Image"

    @property
    def extra_label_lines(self) -> str:
        """Lines for a :file:`Dockerfile` to set the additional labels defined in
        :py:attr:`BaseContainerImage.extra_labels`.

        """
        return "\n".join(f'LABEL {k}="{v}"' for k, v in self.extra_labels.items())

    @property
    def extra_label_xml_lines(self) -> str:
        """XML Elements for a kiwi build description to set the additional labels
        defined in :py:attr:`BaseContainerImage.extra_labels`.

        """
        return "\n".join(
            f'            <label name="{k}" value="{v}"/>'
            for k, v in self.extra_labels.items()
        )

    @property
    def labelprefix(self) -> str:
        """The label prefix used to duplicate the labels. See
        `<https://en.opensuse.org/Building_derived_containers#Labels>`_ for
        further information.

        This value is by default ``com.suse.bci.{self.name}`` unless
        :py:attr:`BaseContainerImage.custom_labelprefix_end` is set. In that
        case it is ``"com.suse.bci.{self.custom_labelprefix_end}"``.

        """
        return f"com.suse.bci.{self.custom_labelprefix_end or self.name}"

    @property
    def kiwi_additional_tags(self) -> Optional[str]:
        """Entry for the ``additionaltags`` attribute in the kiwi build
        description.

        This attribute is used by kiwi to add additional tags to the image under
        it's primary name. This string contains a coma separated list of all
        build tags (except for the primary one) that have the **same** name as
        the image itself.

        """
        extra_tags = []
        for buildtag in self.build_tags[1:]:
            path, tag = buildtag.split(":")
            if path.endswith(self.name):
                extra_tags.append(tag)

        return ",".join(extra_tags) if extra_tags else None

    async def write_files_to_folder(self, dest: str) -> List[str]:
        """Writes all files required to build this image into the destination folder and
        returns the filenames (not full paths) that were written to the disk.

        """
        files = ["_service"]
        tasks = []

        async def write_to_file(
            fname: str, contents: Union[str, bytes], mode="w"
        ) -> None:
            async with aiofiles.open(os.path.join(dest, fname), mode) as f:
                await f.write(contents)

        if self.build_recipe_type == BuildType.DOCKER:
            fname = "Dockerfile"
            tasks.append(
                asyncio.ensure_future(
                    write_to_file(fname, DOCKERFILE_TEMPLATE.render(image=self))
                )
            )
            files.append(fname)

        elif self.build_recipe_type == BuildType.KIWI:
            fname = f"{self.ibs_package}.kiwi"
            tasks.append(
                asyncio.ensure_future(
                    write_to_file(fname, KIWI_TEMPLATE.render(image=self))
                )
            )
            files.append(fname)

            if self.config_sh:
                tasks.append(
                    asyncio.ensure_future(write_to_file("config.sh", self.config_sh))
                )
                files.append("config.sh")

        tasks.append(
            asyncio.ensure_future(
                write_to_file("_service", SERVICE_TEMPLATE.render(image=self))
            )
        )

        changes_file_name = self.ibs_package + ".changes"
        changes_file_dest = os.path.join(dest, changes_file_name)
        if not os.path.exists(changes_file_dest):
            tasks.append(asyncio.ensure_future(write_to_file(changes_file_name, "")))
            files.append(changes_file_name)

        for fname, contents in self.extra_files.items():
            mode = "w" if isinstance(contents, str) else "bw"
            files.append(fname)
            tasks.append(asyncio.ensure_future(write_to_file(fname, contents, mode)))

        await asyncio.gather(*tasks)

        return files


@dataclass
class LanguageStackContainer(BaseContainerImage):
    #: the primary version of the language or application inside this container
    version: Union[str, int] = ""

    #: additional versions that should be added as tags to this container
    additional_versions: List[str] = field(default_factory=list)

    _registry_prefix: str = "bci"

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("A language stack container requires a version")

    @property
    def image_type(self) -> ImageType:
        return ImageType.SLE_BCI

    @property
    def version_label(self) -> str:
        return str(self.version)

    @property
    def nvr(self) -> str:
        return f"{self.name}-{self.version}"

    @property
    def build_tags(self) -> List[str]:
        tags = []
        for name in [self.name] + self.additional_names:
            tags += (
                [f"{self._registry_prefix}/{name}:{self.version_label}"]
                + ([f"{self._registry_prefix}/{name}:latest"] if self.is_latest else [])
                + [f"{self._registry_prefix}/{name}:{self.version_label}-%RELEASE%"]
                + [
                    f"{self._registry_prefix}/{name}:{ver}"
                    for ver in self.additional_versions
                ]
            )
        return tags


@dataclass
class ApplicationStackContainer(LanguageStackContainer):
    def __post_init__(self) -> None:
        self._registry_prefix = "suse"
        super().__post_init__()

    @property
    def image_type(self) -> ImageType:
        return ImageType.APPLICATION


@dataclass
class OsContainer(BaseContainerImage):
    @property
    def nvr(self) -> str:
        return self.name

    @property
    def version_label(self) -> str:
        return "%OS_VERSION_ID_SP%.%RELEASE%"

    @property
    def image_type(self) -> ImageType:
        return ImageType.SLE_BCI

    @property
    def build_tags(self) -> List[str]:
        tags = []
        for name in [self.name] + self.additional_names:
            tags += [
                f"bci/bci-{name}:%OS_VERSION_ID_SP%",
                f"bci/bci-{name}:{self.version_label}",
            ] + ([f"bci/bci-{name}:latest"] if self.is_latest else [])
        return tags


PYTHON_3_6_CONTAINERS = (
    LanguageStackContainer(
        env={"PYTHON_VERSION": "%%py3_ver%%", "PIP_VERSION": "%%pip_ver%%"},
        replacements_via_service=[
            Replacement(regex_in_dockerfile="%%py3_ver%%", package_name="python3-base"),
            Replacement(regex_in_dockerfile="%%pip_ver%%", package_name="python3-pip"),
        ],
        custom_description="Image containing the Python 3.6 development environment based on the SLE Base Container Image.",
        ibs_package=ibs_package,
        build_recipe_type=build_type,
        sp_version=sp_version,
        name="python",
        pretty_name="Python 3.6",
        release_stage=release_stage,
        version="3.6",
        package_list=[
            "python3",
            "python3-pip",
            "python3-wheel",
            "curl",
            "git-core",
        ],
    )
    for (sp_version, ibs_package, build_type, release_stage) in (
        (3, "python-3.6", BuildType.KIWI, ReleaseStage.RELEASED),
        (4, "python-3.6-image", BuildType.DOCKER, ReleaseStage.BETA),
    )
)

_python_kwargs = {
    "name": "python",
    "pretty_name": "Python 3.9",
    "custom_description": "Image containing the Python 3.9 development environment based on the SLE Base Container Image.",
    "version": "3.9",
    "env": {"PYTHON_VERSION": "%%py39_ver%%", "PIP_VERSION": "%%pip_ver%%"},
    "package_list": [
        "python39",
        "python39-pip",
        "curl",
        "git-core",
    ],
    "replacements_via_service": [
        Replacement(regex_in_dockerfile="%%py39_ver%%", package_name="python39-base"),
        Replacement(regex_in_dockerfile="%%pip_ver%%", package_name="python39-pip"),
    ],
    "config_sh_script": r"""rpm -e --nodeps $(rpm -qa|grep libpython3_6) python3-base && \
    ln -s /usr/bin/python3.9 /usr/bin/python3 && \
    ln -s /usr/bin/pip3.9 /usr/bin/pip3 && \
    ln -s /usr/bin/pip3.9 /usr/bin/pip""",
}

PYTHON_3_9_SP3 = LanguageStackContainer(
    release_stage=ReleaseStage.RELEASED,
    ibs_package="python-3.9",
    is_latest=True,
    sp_version=3,
    build_recipe_type=BuildType.KIWI,
    **_python_kwargs,
)

_ruby_kwargs = {
    "name": "ruby",
    "ibs_package": "ruby-2.5-image",
    "pretty_name": "Ruby 2.5",
    "version": "2.5",
    "env": {
        # upstream does this
        "LANG": "C.UTF-8",
        "RUBY_VERSION": "%%rb_ver%%",
        "RUBY_MAJOR": "%%rb_maj%%",
    },
    "replacements_via_service": [
        Replacement(regex_in_dockerfile="%%rb_ver%%", package_name="ruby2.5"),
        Replacement(
            regex_in_dockerfile="%%rb_maj%%",
            package_name="ruby2.5",
            parse_version="minor",
        ),
    ],
    "package_list": [
        "ruby2.5",
        "ruby2.5-rubygem-bundler",
        "ruby2.5-devel",
        "curl",
        "git-core",
        "distribution-release",
        # additional dependencies to build rails, ffi, sqlite3 gems -->
        "gcc-c++",
        "sqlite3-devel",
        "make",
        "awk",
        # additional dependencies supplementing rails
        "timezone",
    ],
    # as we only ship one ruby version, we want to make sure that binaries belonging
    # to our gems get installed as `bin` and not as `bin.ruby2.5`
    "config_sh_script": "sed -i 's/--format-executable/--no-format-executable/' /etc/gemrc",
}
RUBY_CONTAINERS = [
    LanguageStackContainer(
        sp_version=3,
        release_stage=ReleaseStage.RELEASED,
        build_recipe_type=BuildType.KIWI,
        is_latest=True,
        **_ruby_kwargs,
    ),
    LanguageStackContainer(
        sp_version=4, release_stage=ReleaseStage.BETA, **_ruby_kwargs
    ),
]


def _get_golang_kwargs(ver: Literal["1.16", "1.17"], sp_version: int):
    return {
        "sp_version": sp_version,
        "ibs_package": f"golang-{ver}" + ("-image" if sp_version == 4 else ""),
        "custom_description": f"Image containing the Golang {ver} development environment based on the SLE Base Container Image.",
        "release_stage": ReleaseStage.RELEASED if sp_version < 4 else ReleaseStage.BETA,
        "name": "golang",
        "pretty_name": f"Golang {ver}",
        "is_latest": ver == "1.17" and sp_version == 3,
        "version": ver,
        "build_recipe_type": BuildType.KIWI if sp_version == 3 else BuildType.DOCKER,
        "env": {
            "GOLANG_VERSION": ver,
            "PATH": "/go/bin:/usr/local/go/bin:/root/go/bin/:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        },
        "package_list": [
            Package(
                name=name,
                pkg_type=PackageType.BOOTSTRAP
                if sp_version == 3
                else PackageType.IMAGE,
            )
            for name in (f"go{ver}", "distribution-release", "make")
        ],
        "extra_files": {
            # the go binaries are huge and will ftbfs on workers with a root partition with 4GB
            "_constraints": """<constraints>
  <hardware>
    <disk>
      <size unit="G">6</size>
    </disk>
  </hardware>
</constraints>
"""
        },
    }


GOLANG_IMAGES = [
    LanguageStackContainer(**_get_golang_kwargs(ver, sp_version))
    for ver, sp_version in product(("1.16", "1.17"), (3, 4))
]


def _get_node_kwargs(ver: Literal[12, 14, 16], sp_version: SUPPORTED_SLE_SERVICE_PACKS):
    return {
        "name": "nodejs",
        "sp_version": sp_version,
        "release_stage": ReleaseStage.RELEASED
        if sp_version < 4
        else ReleaseStage.RELEASED,
        "is_latest": ver == 14 and sp_version == 3,
        "ibs_package": f"nodejs-{ver}" + ("-image" if sp_version == 4 else ""),
        "build_recipe_type": BuildType.KIWI if sp_version == 3 else BuildType.DOCKER,
        "custom_description": f"Image containing the Node.js {ver} development environment based on the SLE Base Container Image.",
        "additional_names": ["node"],
        "version": str(ver),
        "pretty_name": f"Node.js {ver}",
        "package_list": [
            f"nodejs{ver}",
            # devel dependencies:
            f"npm{ver}",
            "git-core",
            # dependency of nodejs:
            "update-alternatives",
            "distribution-release",
        ],
        "env": {
            "NODE_VERSION": ver,
        },
    }


NODE_CONTAINERS = [
    LanguageStackContainer(**_get_node_kwargs(ver, sp_version))
    for ver, sp_version in product((12, 14, 16), (3, 4))
]


def _get_openjdk_kwargs(sp_version: int, devel: bool):
    JAVA_ENV = {
        "JAVA_BINDIR": "/usr/lib64/jvm/java/bin",
        "JAVA_HOME": "/usr/lib64/jvm/java",
        "JAVA_ROOT": "/usr/lib64/jvm/java",
        "JAVA_VERSION": "11",
    }

    comon = {
        "env": JAVA_ENV,
        "version": 11,
        "sp_version": sp_version,
        "is_latest": sp_version == 3,
        "release_stage": ReleaseStage.RELEASED if sp_version < 4 else ReleaseStage.BETA,
        "build_recipe_type": BuildType.KIWI if sp_version == 3 else BuildType.DOCKER,
        "ibs_package": "openjdk-11"
        + ("-devel" if devel else "")
        + ("-image" if sp_version >= 4 else ""),
    }

    if devel:
        return {
            **comon,
            "name": "openjdk-devel",
            "custom_labelprefix_end": "openjdk.devel",
            "pretty_name": "OpenJDK 11 Development",
            "custom_description": "Image containing the Java 11 Development environment based on the SLE Base Container Image.",
            "package_list": ["java-11-openjdk-devel", "git-core", "maven"],
            "entrypoint": "jshell",
            "from_image": "bci/openjdk:11",
        }
    else:
        return {
            **comon,
            "name": "openjdk",
            "pretty_name": "OpenJDK 11 Runtime",
            "custom_description": "Image containing the Java 11 runtime based on the SLE Base Container Image.",
            "package_list": ["java-11-openjdk"],
        }


OPENJDK_CONTAINERS = [
    LanguageStackContainer(**_get_openjdk_kwargs(sp_version, devel))
    for sp_version, devel in product((3, 4), (True, False))
]


THREE_EIGHT_NINE_DS = ApplicationStackContainer(
    release_stage=ReleaseStage.BETA,
    ibs_package="389-ds-container",
    sp_version=4,
    is_latest=True,
    name="389-ds",
    maintainer="wbrown@suse.de",
    pretty_name="389 Directory Server",
    package_list=["389-ds", "timezone", "openssl"],
    version="1.4",
    custom_end=r"""EXPOSE 3389 3636

RUN mkdir -p /data/config && \
    mkdir -p /data/ssca && \
    mkdir -p /data/run && \
    mkdir -p /var/run/dirsrv && \
    ln -s /data/config /etc/dirsrv/slapd-localhost && \
    ln -s /data/ssca /etc/dirsrv/ssca && \
    ln -s /data/run /var/run/dirsrv

VOLUME /data

HEALTHCHECK --start-period=5m --timeout=5s --interval=5s --retries=2 \
    CMD /usr/lib/dirsrv/dscontainer -H

CMD [ "/usr/lib/dirsrv/dscontainer", "-r" ]
""",
)

INIT_CONTAINERS = [
    OsContainer(
        ibs_package=ibs_package,
        sp_version=sp_version,
        custom_description="Image containing a systemd environment for containers based on the SLE Base Container Image.",
        release_stage=release_stage,
        is_latest=sp_version == 3,
        build_recipe_type=build_recipe_type,
        name="init",
        pretty_name="Init",
        package_list=["systemd", "gzip"],
        entrypoint="/usr/lib/systemd/systemd",
        extra_labels={
            "usage": "This container should only be used to build containers for daemons. Add your packages and enable services using systemctl."
        },
    )
    for (sp_version, release_stage, ibs_package, build_recipe_type) in (
        (3, ReleaseStage.RELEASED, "init", BuildType.KIWI),
        (4, ReleaseStage.BETA, "init-image", BuildType.DOCKER),
    )
]


with open(
    os.path.join(os.path.dirname(__file__), "mariadb", "entrypoint.sh")
) as entrypoint:
    MARIADB_CONTAINERS = [
        LanguageStackContainer(
            ibs_package="mariadb-image",
            sp_version=4,
            release_stage=ReleaseStage.BETA,
            name="mariadb",
            maintainer="bruno.leon@suse.de",
            version="10.6",
            pretty_name="MariaDB Server",
            custom_description="Image containing MariaDB server for RMT, based on the SLE Base Container Image.",
            package_list=["mariadb", "mariadb-tools", "gawk", "timezone", "util-linux"],
            entrypoint='["docker-entrypoint.sh"]',
            extra_files={"docker-entrypoint.sh": entrypoint.read(-1)},
            custom_end=r"""RUN mkdir /docker-entrypoint-initdb.d

VOLUME /var/lib/mysql

# docker-entrypoint from https://github.com/MariaDB/mariadb-docker.git
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh
RUN ln -s usr/local/bin/docker-entrypoint.sh / # backwards compat

RUN sed -i 's#gosu mysql#su mysql -s /bin/bash -m#g' /usr/local/bin/docker-entrypoint.sh

# Ensure all logs goes to stdout
RUN sed -i 's/^log/#log/g' /etc/my.cnf

# Disable binding to localhost only, doesn't make sense in a container
RUN sed -i -e 's|^\(bind-address.*\)|#\1|g' /etc/my.cnf

RUN mkdir /run/mysql

EXPOSE 3306
CMD ["mariadbd"]
""",
        )
    ]


with open(
    os.path.join(os.path.dirname(__file__), "rmt", "entrypoint.sh")
) as entrypoint:
    RMT_CONTAINER = ApplicationStackContainer(
        name="rmt-server",
        ibs_package="suse-rmt-server-container",
        sp_version=4,
        release_stage=ReleaseStage.BETA,
        maintainer="bruno.leon@suse.de",
        pretty_name="RMT Server",
        version="2.7",
        package_list=["rmt-server", "catatonit"],
        entrypoint="/usr/local/bin/entrypoint.sh",
        env={"RAILS_ENV": "production", "LANG": "en"},
        extra_files={"entrypoint.sh": entrypoint.read(-1)},
        custom_end="""COPY entrypoint.sh /usr/local/bin/entrypoint.sh
CMD ["/usr/share/rmt/bin/rails", "server", "-e", "production"]
""",
    )


with open(
    os.path.join(os.path.dirname(__file__), "postgres", "entrypoint.sh")
) as entrypoint:
    _POSTGRES_ENTRYPOINT = entrypoint.read(-1)

with open(
    os.path.join(os.path.dirname(__file__), "postgres", "LICENSE")
) as license_file:
    _POSTGRES_LICENSE = license_file.read(-1)


_POSTGRES_MAJOR_VERSIONS = [14, 13, 12, 10]
POSTGRES_CONTAINERS = [
    ApplicationStackContainer(
        ibs_package=f"postgres-{ver}-image",
        sp_version=4,
        is_latest=ver == 14,
        release_stage=ReleaseStage.BETA,
        name="postgres",
        pretty_name=f"PostgreSQL {ver}",
        package_list=[f"postgresql{ver}-server", "distribution-release"],
        version=ver,
        additional_versions=[f"%%pg_version%%"],
        entrypoint='["docker-entrypoint.sh"]',
        env={
            "LANG": "en_US.utf8",
            "PG_MAJOR": f"{ver}",
            "PG_VERSION": f"%%pg_version%%",
            "PGDATA": "/var/lib/postgresql/data",
        },
        extra_files={
            "docker-entrypoint.sh": _POSTGRES_ENTRYPOINT,
            "LICENSE": _POSTGRES_LICENSE,
        },
        replacements_via_service=[
            Replacement(
                regex_in_dockerfile="%%pg_version%%",
                package_name=f"postgresql{ver}-server",
                parse_version="minor",
            )
        ],
        custom_end=rf"""
VOLUME /var/lib/postgresql/data

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && \
    ln -s su /usr/bin/gosu && \
    mkdir /docker-entrypoint-initdb.d && \
    sed -ri "s|^#?(listen_addresses)\s*=\s*\S+.*|\1 = '*'|" /usr/share/postgresql{ver}/postgresql.conf.sample

STOPSIGNAL SIGINT
EXPOSE 5432
CMD ["postgres"]
""",
    )
    for ver in _POSTGRES_MAJOR_VERSIONS
]


_NGINX_FILES = {}
for filename in (
    "docker-entrypoint.sh",
    "LICENSE",
    "10-listen-on-ipv6-by-default.sh",
    "20-envsubst-on-templates.sh",
    "30-tune-worker-processes.sh",
    "index.html",
):
    with open(os.path.join(os.path.dirname(__file__), "nginx", filename)) as cursor:
        _NGINX_FILES[filename] = cursor.read(-1)


NGINX = ApplicationStackContainer(
    ibs_package="rmt-nginx-image",
    sp_version=4,
    is_latest=True,
    release_stage=ReleaseStage.BETA,
    name="rmt-nginx",
    pretty_name="RMT Nginx",
    version="1.19",
    package_list=["nginx", "distribution-release"],
    entrypoint='["/docker-entrypoint.sh"]',
    extra_files=_NGINX_FILES,
    custom_end="""
RUN mkdir /docker-entrypoint.d
COPY 10-listen-on-ipv6-by-default.sh /docker-entrypoint.d/
COPY 20-envsubst-on-templates.sh /docker-entrypoint.d/
COPY 30-tune-worker-processes.sh /docker-entrypoint.d/
COPY docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
RUN chmod +x /docker-entrypoint.d/20-envsubst-on-templates.sh
RUN chmod +x /docker-entrypoint.d/30-tune-worker-processes.sh
RUN chmod +x /docker-entrypoint.sh

COPY index.html /srv/www/htdocs/

RUN ln -sf /dev/stdout /var/log/nginx/access.log
RUN ln -sf /dev/stderr /var/log/nginx/error.log

EXPOSE 80

STOPSIGNAL SIGQUIT

CMD ["nginx", "-g", "daemon off;"]
""",
)


# PHP_VERSIONS = [7, 8]
# (PHP_7, PHP_8) = (
#     LanguageStackContainer(
#         name="php",
#         pretty_name=f"PHP {ver}",
#         package_list=[
#             f"php{ver}",
#             f"php{ver}-composer",
#             f"php{ver}-zip",
#             f"php{ver}-zlib",
#             f"php{ver}-phar",
#             f"php{ver}-mbstring",
#             "curl",
#             "git-core",
#             "distribution-release",
#         ],
#         version=ver,
#         env={
#             "PHP_VERSION": {7: "7.4.25", 8: "8.0.10"}[ver],
#             "COMPOSER_VERSION": "1.10.22",
#         },
#     )
#     for ver in PHP_VERSIONS
# )


RUST_CONTAINERS = [
    LanguageStackContainer(
        name="rust",
        ibs_package="rust-{ver}-image",
        release_stage=ReleaseStage.BETA,
        sp_version=4,
        is_latest=rust_version == "1.57",
        pretty_name=f"Rust {rust_version}",
        package_list=[
            f"rust{rust_version}",
            f"cargo{rust_version}",
            "distribution-release",
        ],
        version=rust_version,
        env={"RUST_VERSION": rust_version},
    )
    for rust_version in ("1.56", "1.57")
]

MICRO_CONTAINERS = [
    OsContainer(
        name="micro",
        sp_version=sp_version,
        ibs_package=ibs_package,
        is_latest=sp_version == 3,
        pretty_name="%OS_VERSION% Micro",
        custom_description="Image containing a micro environment for containers based on the SLE Base Container Image.",
        release_stage=release_stage,
        from_image=None,
        build_recipe_type=BuildType.KIWI,
        package_list=[
            Package(name, pkg_type=PackageType.BOOTSTRAP)
            for name in (
                "bash",
                "ca-certificates-mozilla-prebuilt",
                "distribution-release",
            )
        ],
        config_sh_script="""
""",
    )
    for sp_version, release_stage, ibs_package in (
        (3, ReleaseStage.RELEASED, "micro"),
        (4, ReleaseStage.BETA, "micro-image"),
    )
]

MINIMAL_CONTAINERS = [
    OsContainer(
        name="minimal",
        from_image="bci/bci-micro",
        sp_version=sp_version,
        is_latest=sp_version == 3,
        ibs_package=ibs_package,
        release_stage=release_stage,
        build_recipe_type=BuildType.KIWI,
        pretty_name="%OS_VERSION% Minimal",
        custom_description="Image containing a minimal environment for containers based on the SLE Base Container Image.",
        package_list=[
            Package(name, pkg_type=PackageType.BOOTSTRAP)
            for name in ("rpm-ndb", "perl-base", "distribution-release")
        ]
        + [
            Package(name, pkg_type=PackageType.DELETE)
            for name in ("grep", "diffutils", "info", "fillup", "libzio1")
        ],
    )
    for sp_version, release_stage, ibs_package in (
        (3, ReleaseStage.RELEASED, "minimal"),
        (4, ReleaseStage.BETA, "minimal-image"),
    )
]

BUSYBOX_CONTAINER = OsContainer(
    name="busybox",
    from_image=None,
    sp_version=4,
    release_stage=ReleaseStage.BETA,
    pretty_name="Busybox",
    ibs_package="busybox-image",
    is_latest=True,
    build_recipe_type=BuildType.KIWI,
    custom_description="Image containing Busybox based on the SLE Base Container Image.",
    entrypoint="/bin/sh",
    package_list=[
        Package(name, pkg_type=PackageType.BOOTSTRAP)
        for name in (
            "busybox",
            "busybox-links",
            "distribution-release",
            "ca-certificates-mozilla-prebuilt",
        )
    ],
)


ALL_CONTAINER_IMAGE_NAMES: Dict[str, BaseContainerImage] = {
    f"{bci.nvr}-sp{bci.sp_version}": bci
    for bci in (
        *PYTHON_3_6_CONTAINERS,
        PYTHON_3_9_SP3,
        THREE_EIGHT_NINE_DS,
        NGINX,
        *RUST_CONTAINERS,
        *GOLANG_IMAGES,
        *RUBY_CONTAINERS,
        *NODE_CONTAINERS,
        *OPENJDK_CONTAINERS,
        *INIT_CONTAINERS,
        *MARIADB_CONTAINERS,
        *POSTGRES_CONTAINERS,
        *MINIMAL_CONTAINERS,
        *MICRO_CONTAINERS,
        BUSYBOX_CONTAINER,
    )
}
ALL_CONTAINER_IMAGE_NAMES.pop("nodejs-16-sp3")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        "Write the contents of a package directly to the filesystem"
    )

    parser.add_argument(
        "image",
        type=str,
        nargs=1,
        choices=list(ALL_CONTAINER_IMAGE_NAMES.keys()),
        help="The BCI container image, which package contents should be written to the disk",
    )
    parser.add_argument(
        "destination",
        type=str,
        nargs=1,
        help="destination folder to which the files should be written",
    )

    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        ALL_CONTAINER_IMAGE_NAMES[args.image[0]].write_files_to_folder(
            args.destination[0]
        )
    )