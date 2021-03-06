"""
Component that will help set the openalpr cloud for alpr processing.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/image_processing.openalpr_cloud/
"""
import asyncio
from base64 import b64encode
import logging

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.core import split_entity_id
from homeassistant.const import CONF_API_KEY
from homeassistant.components.image_processing import (
    PLATFORM_SCHEMA, CONF_CONFIDENCE, CONF_SOURCE, CONF_ENTITY_ID, CONF_NAME)
from homeassistant.components.image_processing.openalpr_local import (
    ImageProcessingAlprEntity)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

OPENALPR_API_URL = "https://api.openalpr.com/v1/recognize"

OPENALPR_REGIONS = [
    'au',
    'auwide',
    'br',
    'eu',
    'fr',
    'gb',
    'kr',
    'kr2',
    'mx',
    'sg',
    'us',
    'vn2'
]

CONF_REGION = 'region'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_API_KEY): cv.string,
    vol.Required(CONF_REGION):
        vol.All(vol.Lower, vol.In(OPENALPR_REGIONS)),
})


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the openalpr cloud api platform."""
    confidence = config[CONF_CONFIDENCE]
    params = {
        'secret_key': config[CONF_API_KEY],
        'tasks': "plate",
        'return_image': 0,
        'country': config[CONF_REGION],
    }

    entities = []
    for camera in config[CONF_SOURCE]:
        entities.append(OpenAlprCloudEntity(
            camera[CONF_ENTITY_ID], params, confidence, camera.get(CONF_NAME)
        ))

    async_add_devices(entities)


class OpenAlprCloudEntity(ImageProcessingAlprEntity):
    """OpenAlpr cloud entity."""

    def __init__(self, camera_entity, params, confidence, name=None):
        """Initialize openalpr local api."""
        super().__init__()

        self._params = params
        self._camera = camera_entity
        self._confidence = confidence

        if name:
            self._name = name
        else:
            self._name = "OpenAlpr {0}".format(
                split_entity_id(camera_entity)[1])

    @property
    def confidence(self):
        """Return minimum confidence for send events."""
        return self._confidence

    @property
    def camera_entity(self):
        """Return camera entity id from process pictures."""
        return self._camera

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @asyncio.coroutine
    def async_process_image(self, image):
        """Process image.

        This method is a coroutine.
        """
        websession = async_get_clientsession(self.hass)
        params = self._params.copy()

        params['image_bytes'] = str(b64encode(image), 'utf-8')

        data = None
        request = None
        try:
            with async_timeout.timeout(self.timeout, loop=self.hass.loop):
                request = yield from websession.post(
                    OPENALPR_API_URL, params=params
                )

                data = yield from request.json()

                if request.status != 200:
                    _LOGGER.error("Error %d -> %s.",
                                  request.status, data.get('error'))
                    return

        except (asyncio.TimeoutError, aiohttp.errors.ClientError):
            _LOGGER.error("Timeout for openalpr api.")
            return

        finally:
            if request is not None:
                yield from request.release()

        # processing api data
        vehicles = 0
        result = {}

        for row in data['plate']['results']:
            vehicles += 1

            for p_data in row['candidates']:
                try:
                    result.update(
                        {p_data['plate']: float(p_data['confidence'])})
                except ValueError:
                    continue

        self.async_process_plates(result, vehicles)
