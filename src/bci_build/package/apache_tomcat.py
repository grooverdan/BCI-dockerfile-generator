"""Provide an Apache Tomcat container."""

from bci_build.package import CAN_BE_LATEST_OS_VERSION
from bci_build.package import DOCKERFILE_RUN
from bci_build.package import _SUPPORTED_UNTIL_SLE
from bci_build.package import OsVersion
from bci_build.package import ParseVersion
from bci_build.package import Replacement

from .appcollection import ApplicationCollectionContainer

_TOMCAT_VERSIONS: list[int] = [9, 10]
assert _TOMCAT_VERSIONS == sorted(_TOMCAT_VERSIONS)

TOMCAT_CONTAINERS = [
    ApplicationCollectionContainer(
        name="apache-tomcat",
        pretty_name=f"Apache Tomcat {tomcat_major}",
        package_name=f"apache-tomcat-{tomcat_major}-image"
        if os_version.is_tumbleweed
        else f"sac-apache-tomcat-{tomcat_major}-image",
        os_version=os_version,
        is_latest=(
            (os_version in CAN_BE_LATEST_OS_VERSION)
            and tomcat_major == _TOMCAT_VERSIONS[-1]
            and os_version.is_tumbleweed
        ),
        version=tomcat_major,
        supported_until=_SUPPORTED_UNTIL_SLE.get(os_version),
        additional_versions=["%%tomcat_version%%", "%%tomcat_minor%%"],
        package_list=[
            tomcat_pkg := (
                "tomcat"
                if tomcat_major == _TOMCAT_VERSIONS[0]
                else f"tomcat{tomcat_major}"
            )
        ]
        + (
            ["java-21-openjdk", "java-21-openjdk-headless"]
            if os_version == OsVersion.SP6
            else []
        ),
        replacements_via_service=[
            Replacement(
                regex_in_build_description="%%tomcat_version%%", package_name=tomcat_pkg
            ),
            Replacement(
                regex_in_build_description="%%tomcat_minor%%",
                package_name=tomcat_pkg,
                parse_version=ParseVersion.MINOR,
            ),
        ],
        cmd=[
            f"/usr/{'libexec' if os_version in( OsVersion.TUMBLEWEED, OsVersion.BASALT) else 'lib'}/tomcat/server",
            "start",
        ],
        exposes_tcp=[8080],
        env={
            "TOMCAT_MAJOR": tomcat_major,
            "TOMCAT_VERSION": "%%tomcat_version%%",
            "CATALINA_HOME": (_CATALINA_HOME := "/usr/share/tomcat"),
            "CATALINA_BASE": _CATALINA_HOME,
            "PATH": f"{_CATALINA_HOME}/bin:$PATH",
        },
        custom_end=rf"""{DOCKERFILE_RUN} mkdir -p /var/log/tomcat; chown --recursive tomcat:tomcat /var/log/tomcat;
{DOCKERFILE_RUN} \
    sed -i /etc/tomcat/logging.properties \
        -e 's|org\.apache\.catalina\.core\.ContainerBase\.\[Catalina\]\.\[localhost\]\.handlers =.*|org.apache.catalina.core.ContainerBase.[Catalina].[localhost].handlers = java.util.logging.ConsoleHandler|' \
        -e 's|org\.apache\.catalina\.core\.ContainerBase\.\[Catalina\]\.\[localhost\]\.\[/manager\]\.handlers =.*|org.apache.catalina.core.ContainerBase.[Catalina].[localhost].[/manager].handlers = java.util.logging.ConsoleHandler|' \
        -e 's|org\.apache\.catalina\.core\.ContainerBase\.\[Catalina\]\.\[localhost\]\.\[/host-manager\]\.handlers =.*|org.apache.catalina.core.ContainerBase.[Catalina].[localhost].[/host-manager].handlers = java.util.logging.ConsoleHandler|'

WORKDIR $CATALINA_HOME
""",
        entrypoint_user="tomcat",
        logo_url="https://tomcat.apache.org/res/images/tomcat.png",
    )
    for tomcat_major, os_version in (
        (10, OsVersion.TUMBLEWEED),
        (9, OsVersion.TUMBLEWEED),
        (10, OsVersion.SP6),
    )
]