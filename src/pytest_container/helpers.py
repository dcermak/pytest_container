def auto_container_parametrize(metafunc):
    container_images = getattr(metafunc.module, "CONTAINER_IMAGES", None)
    if container_images is not None:
        for fixture_name in ("auto_container", "auto_container_per_test"):
            if fixture_name in metafunc.fixturenames:
                metafunc.parametrize(
                    fixture_name, container_images, indirect=True
                )
