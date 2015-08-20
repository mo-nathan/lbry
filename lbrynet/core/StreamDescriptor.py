from collections import defaultdict
import json
import logging
from twisted.internet import threads
from lbrynet.core.client.StandaloneBlobDownloader import StandaloneBlobDownloader


class StreamDescriptorReader(object):
    """Classes which derive from this class read a stream descriptor file return
       a dictionary containing the fields in the file"""
    def __init__(self):
        pass

    def _get_raw_data(self):
        """This method must be overridden by subclasses. It should return a deferred
           which fires with the raw data in the stream descriptor"""
        pass

    def get_info(self):
        """Return the fields contained in the file"""
        d = self._get_raw_data()
        d.addCallback(json.loads)
        return d


class PlainStreamDescriptorReader(StreamDescriptorReader):
    """Read a stream descriptor file which is not a blob but a regular file"""
    def __init__(self, stream_descriptor_filename):
        StreamDescriptorReader.__init__(self)
        self.stream_descriptor_filename = stream_descriptor_filename

    def _get_raw_data(self):

        def get_data():
            with open(self.stream_descriptor_filename) as file_handle:
                raw_data = file_handle.read()
                return raw_data

        return threads.deferToThread(get_data)


class BlobStreamDescriptorReader(StreamDescriptorReader):
    """Read a stream descriptor file which is a blob"""
    def __init__(self, blob):
        StreamDescriptorReader.__init__(self)
        self.blob = blob

    def _get_raw_data(self):

        def get_data():
            f = self.blob.open_for_reading()
            if f is not None:
                raw_data = f.read()
                self.blob.close_read_handle(f)
                return raw_data
            else:
                raise ValueError("Could not open the blob for reading")

        return threads.deferToThread(get_data)


class StreamDescriptorWriter(object):
    """Classes which derive from this class write fields from a dictionary
       of fields to a stream descriptor"""
    def __init__(self):
        pass

    def create_descriptor(self, sd_info):
        return self._write_stream_descriptor(json.dumps(sd_info))

    def _write_stream_descriptor(self, raw_data):
        """This method must be overridden by subclasses to write raw data to the stream descriptor"""
        pass


class PlainStreamDescriptorWriter(StreamDescriptorWriter):
    def __init__(self, sd_file_name):
        StreamDescriptorWriter.__init__(self)
        self.sd_file_name = sd_file_name

    def _write_stream_descriptor(self, raw_data):

        def write_file():
            logging.debug("Writing the sd file to disk")
            with open(self.sd_file_name, 'w') as sd_file:
                sd_file.write(raw_data)
            return self.sd_file_name

        return threads.deferToThread(write_file)


class BlobStreamDescriptorWriter(StreamDescriptorWriter):
    def __init__(self, blob_manager):
        StreamDescriptorWriter.__init__(self)

        self.blob_manager = blob_manager

    def _write_stream_descriptor(self, raw_data):
        logging.debug("Creating the new blob for the stream descriptor")
        blob_creator = self.blob_manager.get_blob_creator()
        blob_creator.write(raw_data)
        logging.debug("Wrote the data to the new blob")
        return blob_creator.close()


class StreamDescriptorIdentifier(object):
    """Tries to determine the type of stream described by the stream descriptor using the
       'stream_type' field. Keeps a list of StreamDescriptorValidators and StreamDownloaderFactorys
       and returns the appropriate ones based on the type of the stream descriptor given
    """
    def __init__(self):
        self._sd_info_validators = {}  # {stream_type: IStreamDescriptorValidator}
        self._stream_downloader_factories = defaultdict(list)  # {stream_type: [IStreamDownloaderFactory]}

    def add_stream_info_validator(self, stream_type, sd_info_validator):
        """
        This is how the StreamDescriptorIdentifier learns about new types of stream descriptors.

        There can only be one StreamDescriptorValidator for each type of stream.

        @param stream_type: A string representing the type of stream descriptor. This must be unique to
            this stream descriptor.

        @param sd_info_validator: A class implementing the IStreamDescriptorValidator interface. This class's
            constructor will be passed the raw metadata in the stream descriptor file and its 'validate' method
            will then be called. If the validation step fails, an exception will be thrown, preventing the stream
            descriptor from being further processed.

        @return: None
        """
        self._sd_info_validators[stream_type] = sd_info_validator

    def add_stream_downloader_factory(self, stream_type, factory):
        """
        Register a stream downloader factory with the StreamDescriptorIdentifier.

        This is how the StreamDescriptorIdentifier determines what factories may be used to process different stream
        descriptor files. There must be at least one factory for each type of stream added via
        "add_stream_info_validator".

        @param stream_type: A string representing the type of stream descriptor which the factory knows how to process.

        @param factory: An object implementing the IStreamDownloaderFactory interface.

        @return: None
        """
        self._stream_downloader_factories[stream_type].append(factory)

    def get_info_and_factories_for_sd_file(self, sd_path):

        sd_reader = PlainStreamDescriptorReader(sd_path)
        d = sd_reader.get_info()
        d.addCallback(self._return_info_and_factories)
        return d

    def get_info_and_factories_for_sd_blob(self, sd_blob):
        sd_reader = BlobStreamDescriptorReader(sd_blob)
        d = sd_reader.get_info()
        d.addCallback(self._return_info_and_factories)
        return d

    def _get_factories(self, stream_type):
        assert stream_type in self._stream_downloader_factories, "Unrecognized stream type: " + str(stream_type)
        return self._stream_downloader_factories[stream_type]

    def _get_validator(self, stream_type):
        assert stream_type in self._sd_info_validators, "Unrecognized stream type: " + str(stream_type)
        return self._sd_info_validators[stream_type]

    def _return_info_and_factories(self, sd_info):
        assert 'stream_type' in sd_info, 'Invalid stream descriptor. No stream_type parameter.'
        stream_type = sd_info['stream_type']
        factories = self._get_factories(stream_type)
        validator = self._get_validator(stream_type)(sd_info)
        d = validator.validate()

        d.addCallback(lambda _: (validator, factories))
        return d


def download_sd_blob(session, blob_hash, payment_rate_manager):
    """
    Downloads a single blob from the network

    @param session:

    @param blob_hash:

    @param payment_rate_manager:

    @return: An object of type HashBlob
    """
    downloader = StandaloneBlobDownloader(blob_hash, session.blob_manager, session.peer_finder,
                                          session.rate_limiter, payment_rate_manager, session.wallet)
    return downloader.download()