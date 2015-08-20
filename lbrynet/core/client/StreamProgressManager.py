import logging
from lbrynet.interfaces import IProgressManager
from twisted.internet import defer
from zope.interface import implements


class StreamProgressManager(object):
    implements(IProgressManager)

    def __init__(self, finished_callback, blob_manager, download_manager, delete_blob_after_finished=False):
        self.finished_callback = finished_callback
        self.blob_manager = blob_manager
        self.delete_blob_after_finished = delete_blob_after_finished
        self.download_manager = download_manager
        self.provided_blob_nums = []
        self.last_blob_outputted = -1
        self.stopped = True
        self._next_try_to_output_call = None
        self.outputting_d = None

    ######### IProgressManager #########

    def start(self):

        from twisted.internet import reactor

        self.stopped = False
        self._next_try_to_output_call = reactor.callLater(0, self._try_to_output)
        return defer.succeed(True)

    def stop(self):
        self.stopped = True
        if self._next_try_to_output_call is not None and self._next_try_to_output_call.active():
            self._next_try_to_output_call.cancel()
        self._next_try_to_output_call = None
        return self._stop_outputting()

    def blob_downloaded(self, blob, blob_num):
        if self.outputting_d is None:
            self._output_loop()

    ######### internal #########

    def _finished_outputting(self):
        self.finished_callback(True)

    def _try_to_output(self):

        from twisted.internet import reactor

        self._next_try_to_output_call = reactor.callLater(1, self._try_to_output)
        if self.outputting_d is None:
            self._output_loop()

    def _output_loop(self):
        pass

    def _stop_outputting(self):
        if self.outputting_d is not None:
            return self.outputting_d
        return defer.succeed(None)

    def _finished_with_blob(self, blob_num):
        logging.debug("In _finished_with_blob, blob_num = %s", str(blob_num))
        if self.delete_blob_after_finished is True:
            logging.debug("delete_blob_after_finished is True")
            blobs = self.download_manager.blobs
            if blob_num in blobs:
                logging.debug("Telling the blob manager, %s,  to delete blob %s", str(self.blob_manager),
                              blobs[blob_num].blob_hash)
                self.blob_manager.delete_blobs([blobs[blob_num].blob_hash])
            else:
                logging.debug("Blob number %s was not in blobs", str(blob_num))
        else:
            logging.debug("delete_blob_after_finished is False")


class FullStreamProgressManager(StreamProgressManager):
    def __init__(self, finished_callback, blob_manager, download_manager, delete_blob_after_finished=False):
        StreamProgressManager.__init__(self, finished_callback, blob_manager, download_manager,
                                       delete_blob_after_finished)
        self.outputting_d = None

    ######### IProgressManager #########

    def stream_position(self):
        blobs = self.download_manager.blobs
        if not blobs:
            return 0
        else:
            for i in xrange(max(blobs.iterkeys())):
                if not i in blobs or (not blobs[i].is_validated() and not i in self.provided_blob_nums):
                    return i
            return max(blobs.iterkeys()) + 1

    def needed_blobs(self):
        blobs = self.download_manager.blobs
        return [b for n, b in blobs.iteritems() if not b.is_validated() and not n in self.provided_blob_nums]

    ######### internal #########

    def _output_loop(self):

        from twisted.internet import reactor

        if self.stopped:
            if self.outputting_d is not None:
                self.outputting_d.callback(True)
                self.outputting_d = None
            return

        if self.outputting_d is None:
            self.outputting_d = defer.Deferred()
        blobs = self.download_manager.blobs

        def finished_outputting_blob():
            self.last_blob_outputted += 1
            final_blob_num = self.download_manager.final_blob_num()
            if final_blob_num is not None and final_blob_num == self.last_blob_outputted:
                self._finished_outputting()
                self.outputting_d.callback(True)
                self.outputting_d = None
            else:
                reactor.callLater(0, self._output_loop)

        current_blob_num = self.last_blob_outputted + 1

        if current_blob_num in blobs and blobs[current_blob_num].is_validated():
            logging.info("Outputting blob %s", str(self.last_blob_outputted + 1))
            self.provided_blob_nums.append(self.last_blob_outputted + 1)
            d = self.download_manager.handle_blob(self.last_blob_outputted + 1)
            d.addCallback(lambda _: finished_outputting_blob())
            d.addCallback(lambda _: self._finished_with_blob(current_blob_num))

            def log_error(err):
                logging.warning("Error occurred in the output loop. Error: %s", err.getErrorMessage())

            d.addErrback(log_error)
        else:
            self.outputting_d.callback(True)
            self.outputting_d = None