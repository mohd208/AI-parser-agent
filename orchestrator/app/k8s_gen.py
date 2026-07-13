from pathlib import Path

from .language_detect import DetectedRuntime
from .models import JiraTicket
from .templating import write_rendered

_MANIFESTS = ["namespace", "serviceaccount-irsa", "deployment", "service", "ingress", "hpa"]


def generate(repo_path: Path, ticket: JiraTicket, runtime: DetectedRuntime) -> list[str]:
    app = ticket.application_name.lower().replace(" ", "-")
    environment = ticket.environment
    # Naming convention: every object/resource name is <application>-<environment>,
    # so dev/staging/prod of the same app never collide, whether you're looking
    # at `kubectl get deploy -A`, ECR, or IAM.
    resource_name = f"{app}-{environment}"

    ctx = dict(
        app_name=app,
        resource_name=resource_name,
        namespace=resource_name,
        environment=environment,
        port=runtime.port,
        # Substituted by the deploy workflow with the real ECR image URI, image
        # tag, and IRSA role ARN (the URI/role ARN come from this app's
        # terraform output). Nothing AWS-account-specific is baked into the
        # committed manifest.
        image_uri_placeholder="__IMAGE_URI__",
        image_tag_placeholder="__IMAGE_TAG__",
        irsa_role_arn_placeholder="__IRSA_ROLE_ARN__",
    )

    written = []
    for name in _MANIFESTS:
        dest = repo_path / "k8s" / environment / f"{name.replace('-irsa', '')}.yaml"
        write_rendered(f"k8s/{name}.yaml.j2", dest, **ctx)
        written.append(str(dest.relative_to(repo_path)))
    return written
