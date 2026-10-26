import classNames from 'classnames';
import { CircleAlert, CircleCheck, Info, LoaderCircle, X } from 'lucide-react';
import { hideMessage, useMessages } from 'App/messagesStore';
import Icon from 'Components/Icon';
import IconButton from 'Components/Link/IconButton';
import styles from './Messages.module.css';

const ICONS = { info: Info, success: CircleCheck, warning: CircleAlert, danger: CircleAlert };

function Messages() {
  const messages = useMessages();

  if (!messages.length) {
    return null;
  }

  return (
    <div className={styles.messages} aria-live="polite">
      {messages.map((message) => (
        <div key={message.id} className={classNames(styles.message, styles[message.kind])}>
          <Icon
            className={styles.icon}
            name={message.isWorking ? LoaderCircle : ICONS[message.kind]}
            isSpinning={message.isWorking}
          />
          <span className={styles.text}>{message.text}</span>
          {message.isWorking ? null : (
            <IconButton name={X} size={14} aria-label="Dismiss" onPress={() => hideMessage(message.id)} />
          )}
        </div>
      ))}
    </div>
  );
}

export default Messages;
