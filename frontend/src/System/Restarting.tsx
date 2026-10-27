// Sonarr's restarting overlay: LazyLibrarian is restarting, after a restore, an update or Restart,
// so wait for it to answer again, then load the page afresh
import { useEffect } from 'react';
import { LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalHeader } from 'Components/Modal/Modal';
import { urlBase } from 'Utilities/api';

const POLL = 2000;
// it answers until it has stopped, so give it a moment before asking
const FIRST_LOOK = 5000;

async function isUp() {
  try {
    const response = await fetch(`${urlBase()}/ping`, { cache: 'no-store' });
    return response.ok;
  } catch {
    return false;
  }
}

function Restarting({ isOpen, message }: { isOpen: boolean; message: string }) {
  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    let timer = 0;
    let wentDown = false;
    const started = Date.now();

    async function look() {
      const up = await isUp();

      wentDown = wentDown || !up;

      if (up && (wentDown || Date.now() - started > 60000)) {
        window.location.reload();
        return;
      }

      timer = window.setTimeout(look, POLL);
    }

    timer = window.setTimeout(look, FIRST_LOOK);

    return () => window.clearTimeout(timer);
  }, [isOpen]);

  return (
    <Modal isOpen={isOpen} size="small" onModalClose={() => undefined}>
      <ModalContent onModalClose={() => undefined}>
        <ModalHeader>Restarting</ModalHeader>
        <ModalBody>
          <p>{message}</p>
          <LoadingIndicator />
          <p>The page loads again when LazyLibrarian is back.</p>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}

export default Restarting;
