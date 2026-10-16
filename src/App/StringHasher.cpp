// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************************************
 *                                                                                                 *
 *   Copyright (c) 2022 Zheng, Lei (realthunder) <realthunder.dev@gmail.com>                       *
 *   Copyright (c) 2023 FreeCAD Project Association                                                *
 *                                                                                                 *
 *   This file is part of FreeCAD.                                                                 *
 *                                                                                                 *
 *   FreeCAD is free software: you can redistribute it and/or modify it under the terms of the     *
 *   GNU Lesser General Public License as published by the Free Software Foundation, either        *
 *   version 2.1 of the License, or (at your option) any later version.                            *
 *                                                                                                 *
 *   FreeCAD is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;          *
 *   without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.     *
 *   See the GNU Lesser General Public License for more details.                                   *
 *                                                                                                 *
 *   You should have received a copy of the GNU Lesser General Public License along with           *
 *   FreeCAD. If not, see <https://www.gnu.org/licenses/>.                                         *
 *                                                                                                 *
 **************************************************************************************************/


#include <QCryptographicHash>
#include <QHash>
#include <deque>
#include <functional>

#include <Base/Console.h>
#include <Base/Reader.h>
#include <Base/Stream.h>
#include <Base/Tools.h>
#include <Base/Writer.h>

#include <boost/algorithm/string/classification.hpp>
#include <boost/algorithm/string/split.hpp>
#include <boost/bimap.hpp>
#include <boost/bimap/set_of.hpp>
#include <boost/bimap/unordered_set_of.hpp>
#include <boost/functional/hash.hpp>
#include <boost/io/ios_state.hpp>
#include <boost/iostreams/stream.hpp>

#include "MappedElement.h"
#include "ElementNamingUtils.h"
#include "StringHasher.h"
#include "StringHasherPy.h"
#include "StringIDPy.h"


FC_LOG_LEVEL_INIT("App", true, true)

namespace bio = boost::iostreams;
using namespace App;

///////////////////////////////////////////////////////////

struct StringIDHasher
{
    static unsigned semanticFlags(const StringID& sid)
    {
        // Marked and Persistent are mutable lifetime policy, not identity data.
        return unsigned(sid.isBinary()) | (unsigned(sid.isHashed()) << 1)
            | (unsigned(sid.isPostfixEncoded()) << 2) | (unsigned(sid.isPostfixed()) << 3)
            | (unsigned(sid.isIndexed()) << 4) | (unsigned(sid.isPrefixID()) << 5)
            | (unsigned(sid.isPrefixIDIndex()) << 6);
    }

    std::size_t operator()(const StringID* sid) const
    {
        if (!sid) {
            return 0;
        }
        std::size_t result = qHash(sid->data(), qHash(sid->postfix()));
        boost::hash_combine(result, semanticFlags(*sid));
        for (const auto& related : sid->relatedIDs()) {
            boost::hash_combine(result, related.value());
        }
        return result;
    }

    bool operator()(const StringID* IDa, const StringID* IDb) const
    {
        if (IDa == IDb) {
            return true;
        }
        if (!IDa || !IDb) {
            return false;
        }
        const auto& a = IDa->relatedIDs();
        const auto& b = IDb->relatedIDs();
        return IDa->data() == IDb->data() && IDa->postfix() == IDb->postfix()
            && semanticFlags(*IDa) == semanticFlags(*IDb) && a.size() == b.size()
            && std::equal(a.begin(), a.end(), b.begin(), [](const auto& first, const auto& second) {
                   // Related identities retain their core data; reference indices
                   // live in the encoded name and are not part of this graph.
                   // Construction and import keep all dependencies in this
                   // same table, so the core numeric IDs are unambiguous.
                   return first.value() == second.value();
               });
    }
};

using HashMapBase =
    boost::bimap<boost::bimaps::unordered_set_of<StringID*, StringIDHasher, StringIDHasher>,
                 boost::bimaps::set_of<long>>;

class StringHasher::HashMap: public HashMapBase
{
public:
    bool SaveAll = false;
    int Threshold = 0;
};

///////////////////////////////////////////////////////////

TYPESYSTEM_SOURCE_ABSTRACT(App::StringID, Base::BaseClass)

StringID::~StringID()
{
    if (_hasher) {
        _hasher->_hashes->right.erase(_id);
    }
}

PyObject* StringID::getPyObject()
{
    return new StringIDPy(this);
}

PyObject* StringID::getPyObjectWithIndex(int index)
{
    auto res = new StringIDPy(this);
    res->_index = index;
    return res;
}

std::string StringID::toString(int index) const
{
    std::ostringstream ss;
    ss << '#' << std::hex << value();
    if (index != 0) {
        ss << ':' << index;
    }
    return ss.str();
}

StringID::IndexID StringID::fromString(const char* name, bool eof, int size)
{
    IndexID res {};
    res.id = 0;
    res.index = 0;
    if (!name) {
        res.id = -1;
        return res;
    }
    if (size < 0) {
        size = static_cast<int>(std::strlen(name));
    }
    bio::stream<bio::array_source> iss(name, size);
    char sep = 0;
    char sep2 = 0;
    iss >> sep >> std::hex >> res.id >> sep2 >> res.index;
    if ((eof && !iss.eof()) || sep != '#' || (sep2 != 0 && sep2 != ':')) {
        res.id = -1;
        return res;
    }
    return res;
}

std::string StringID::dataToText(int index) const
{
    if (isHashed() || isBinary()) {
        return _data.toBase64().constData();
    }

    std::string res(_data.constData());
    if (index != 0) {
        res += std::to_string(index);
    }
    if (_postfix.size() != 0) {
        res += _postfix.constData();
    }
    return res;
}

void StringID::mark() const
{
    if (isMarked()) {
        return;
    }
    _flags.setFlag(Flag::Marked);
    for (auto& sid : _sids) {
        sid.deref().mark();
    }
}

///////////////////////////////////////////////////////////

TYPESYSTEM_SOURCE(App::StringHasher, Base::Persistence)

StringHasher::StringHasher()
    : _hashes(new HashMap)
{}

StringHasher::~StringHasher()
{
    clear();
}

void StringHasher::setSaveAll(bool enable)
{
    if (_hashes->SaveAll == enable) {
        return;
    }
    _hashes->SaveAll = enable;
    compact();
}

void StringHasher::compact()
{
    if (_hashes->SaveAll) {
        return;
    }

    // Make a list of all the table entries that have only a single reference and are not marked
    // "persistent"
    std::deque<StringIDRef> pendings;
    for (auto& hasher : _hashes->right) {
        if (!hasher.second->isPersistent() && hasher.second->getRefCount() == 1) {
            pendings.emplace_back(hasher.second);
        }
    }

    // Recursively remove the unused StringIDs
    while (!pendings.empty()) {
        StringIDRef sid = pendings.front();
        pendings.pop_front();
        // Try to erase the map entry for this StringID
        if (_hashes->right.erase(sid.value()) == 0U) {
            continue;  // If nothing was erased, there's nothing more to do
        }
        sid._sid->_hasher = nullptr;
        sid._sid->unref();
        for (auto& hasher : sid._sid->_sids) {
            if (hasher._sid->_hasher == this && !hasher._sid->isPersistent()
                && hasher._sid->getRefCount() == 2) {
                // If the related StringID also uses this hasher, is not marked persistent, and has
                // a current reference count of 2 (which will be its hasher reference and its entry
                // in the related SIDs list), then prep it for removal as well.
                pendings.push_back(hasher);
            }
        }
    }
}

bool StringHasher::getSaveAll() const
{
    return _hashes->SaveAll;
}

void StringHasher::setThreshold(int threshold)
{
    _hashes->Threshold = threshold;
}

int StringHasher::getThreshold() const
{
    return _hashes->Threshold;
}

long StringHasher::lastID() const
{
    if (_hashes->right.empty()) {
        return 0;
    }
    auto it = _hashes->right.end();
    --it;
    return it->first;
}

StringIDRef StringHasher::getID(const char* text, int len, bool hashable)
{
    if (len < 0) {
        len = static_cast<int>(strlen(text));
    }
    return getID(QByteArray::fromRawData(text, len), hashable ? Option::Hashable : Option::None);
}

StringIDRef StringHasher::getID(const QByteArray& data, Options options)
{
    bool binary = options.testFlag(Option::Binary);
    bool hashable = options.testFlag(Option::Hashable);
    bool nocopy = options.testFlag(Option::NoCopy);

    bool hashed = hashable && _hashes->Threshold > 0 && (int)data.size() > _hashes->Threshold;

    StringID dataID;
    if (hashed) {
        QCryptographicHash hasher(QCryptographicHash::Sha1);
        hasher.addData(data);
        dataID._data = hasher.result();
    }
    else {
        dataID._data = data;
    }
    dataID._flags.setFlag(StringID::Flag::Binary, binary);
    dataID._flags.setFlag(StringID::Flag::Hashed, hashed);

    auto it = _hashes->left.find(&dataID);
    if (it != _hashes->left.end()) {
        return {it->first};
    }

    if (!hashed && !nocopy) {
        // if not hashed, make a deep copy of the data
        dataID._data = QByteArray(data.constData(), data.size());
    }

    StringIDRef sid(new StringID(lastID() + 1, dataID._data, dataID._flags));
    return {insert(sid)};
}

StringIDRef StringHasher::getID(const Data::MappedName& name, const QVector<StringIDRef>& sids)
{
    StringID tempID;
    tempID._postfix = name.postfixBytes();

    Data::IndexedName indexed;
    if (tempID._postfix.size() != 0) {
        // Only check for IndexedName if there is postfix, because of the way
        // we restore the StringID. See StringHasher::saveStream/restoreStreamNew()
        indexed = Data::IndexedName(name.dataBytes());
    }
    if (indexed) {
        // If this is an IndexedName, then _data only stores the base part of the name, without the
        // integer index
        tempID._data =
            QByteArray::fromRawData(indexed.getType(), static_cast<int>(strlen(indexed.getType())));
    }
    else {
        // Store the entire name in _data, but temporarily reuse the existing memory
        tempID._data = name.dataBytes();
    }

    if (!indexed && name.isRaw()) {
        // Make a copy of the memory if we didn't do so earlier
        tempID._data = QByteArray(name.dataBytes().constData(), name.dataBytes().size());
    }

    // If the postfix is not already encoded, use getID to encode it:
    StringIDRef postfixRef;
    if ((tempID._postfix.size() != 0) && tempID._postfix.indexOf("#") < 0) {
        postfixRef = getID(tempID._postfix);
        postfixRef.toBytes(tempID._postfix);
    }

    // If _data is an IndexedName, use getID to encode it:
    StringIDRef indexRef;
    if (indexed) {
        // Restore reconstructs the indexed type from this dependency. Its
        // literal spelling must survive even a very small hashing threshold.
        indexRef = getID(tempID._data, Option::None);
    }

    // The real StringID object that we are going to insert
    StringIDRef newStringIDRef(new StringID(lastID() + 1, tempID._data));
    StringID& newStringID = *newStringIDRef._sid;
    if (tempID._postfix.size() != 0) {
        newStringID._flags.setFlag(StringID::Flag::Postfixed);
        newStringID._postfix = tempID._postfix;
    }

    // Count the related SIDs that use this hasher
    int numSIDs = 0;
    for (const auto& relatedID : sids) {
        if (relatedID && relatedID._sid->_hasher == this) {
            ++numSIDs;
        }
    }

    int numAddedSIDs = (postfixRef ? 1 : 0) + (indexRef ? 1 : 0);
    if (numSIDs == sids.size() && !postfixRef && !indexRef) {
        // The simplest case: just copy the whole list
        newStringID._sids = sids;
    }
    else {
        // Put the added SIDs at the front of the SID list
        newStringID._sids.reserve(numSIDs + numAddedSIDs);
        if (postfixRef) {
            newStringID._flags.setFlag(StringID::Flag::PostfixEncoded);
            newStringID._sids.push_back(postfixRef);
        }
        if (indexRef) {
            newStringID._flags.setFlag(StringID::Flag::Indexed);
            newStringID._sids.push_back(indexRef);
        }
        // Append the sids from the input list whose hasher is this one
        for (const auto& relatedID : sids) {
            if (relatedID && relatedID._sid->_hasher == this) {
                newStringID._sids.push_back(relatedID);
            }
        }
    }

    // If the number of related IDs is larger than some threshold (hardcoded to 10 right now), then
    // remove any duplicates (ignoring the new SIDs we may have just added)
    const int relatedIDSizeThreshold {10};
    if (newStringID._sids.size() > relatedIDSizeThreshold) {
        std::sort(newStringID._sids.begin() + numAddedSIDs, newStringID._sids.end());
        newStringID._sids.erase(
            std::unique(newStringID._sids.begin() + numAddedSIDs, newStringID._sids.end()),
            newStringID._sids.end());
    }

    // If the new StringID has a postfix, but is not indexed, see if the data string itself
    // contains an index.
    if ((newStringID._postfix.size() != 0) && !indexed) {
        // Use the fromString function to parse the new StringID's data field for a possible index
        StringID::IndexID res = StringID::fromString(newStringID._data);
        if (res.id > 0) {  // If the data had an index
            if (res.index != 0) {
                indexed.setIndex(res.index);
                newStringID._data.resize(newStringID._data.lastIndexOf(':') + 1);
            }
            int offset = newStringID.isPostfixEncoded() ? 1 : 0;
            // Search for the SID with that index
            for (int i = offset; i < newStringID._sids.size(); ++i) {
                if (newStringID._sids[i].value() == res.id) {
                    if (i != offset) {
                        // If this SID is not already the first element in sids, move it there by
                        // swapping it with whatever WAS there
                        std::swap(newStringID._sids[offset], newStringID._sids[i]);
                    }
                    if (res.index != 0) {
                        newStringID._flags.setFlag(StringID::Flag::PrefixIDIndex);
                    }
                    else {
                        newStringID._flags.setFlag(StringID::Flag::PrefixID);
                    }
                    break;
                }
            }
        }
    }

    // The identity includes its encoding flags and dependency graph. Looking it
    // up before those are complete could alias an equal payload from another
    // encoding or identity domain.
    auto it = _hashes->left.find(&newStringID);
    if (it != _hashes->left.end()) {
        return {it->first, indexed.getIndex()};
    }
    return {insert(newStringIDRef), indexed.getIndex()};
}

StringHasher::Importer::Importer(StringHasherRef target)
    : _target(std::move(target))
{
    if (!_target) {
        throw Base::ValueError("A target string hasher is required");
    }
}

namespace
{
QByteArray translateMappedReferences(
    const QByteArray& text,
    const QVector<StringIDRef>& references,
    const StringHasherRef& source,
    const std::function<StringIDRef(const StringIDRef&)>& translateID,
    const std::set<const StringID*>& pending,
    const std::function<void(const StringIDRef&)>& retain = {}
);
}

StringIDRef StringHasher::Importer::importID(const StringIDRef& source)
{
    if (!source || source.isFromSameHasher(_target)) {
        return source;
    }
    const auto& original = source.deref();
    auto found = _imported.find(&original);
    if (found != _imported.end()) {
        return {found->second.second, source.getIndex()};
    }
    if (!_pending.insert(&original).second) {
        throw Base::RuntimeError("Cyclic string identity references");
    }
    Base::ScopeGuard guard([&]() { _pending.erase(&original); });

    auto flags = original._flags;
    flags.setFlag(StringID::Flag::Marked, false);
    StringIDRef imported(
        new StringID(0, QByteArray(original._data.constData(), original._data.size()), flags)
    );
    auto& result = *imported._sid;
    result._postfix = QByteArray(original._postfix.constData(), original._postfix.size());
    result._sids.reserve(original._sids.size());
    for (const auto& related : original._sids) {
        result._sids.push_back(importID(related));
    }
    auto translate = [&](const QByteArray& bytes) {
        return translateMappedReferences(
            bytes,
            original._sids,
            original.getHasher(),
            [this](const auto& sid) { return importID(sid); },
            _pending,
            [&](const auto& sid) {
                auto found = std::find_if(result._sids.begin(), result._sids.end(), [&](const auto& r) {
                    return r.value() == sid.value() && r.getHasher() == sid.getHasher();
                });
                if (found == result._sids.end()) {
                    // Native tagged combo leaves can carry encoded references
                    // whose original retention graph lived only on their parent.
                    result._sids.emplace_back(sid, 0);
                }
            }
        );
    };

    // Opaque payloads are already hashed (or explicitly binary): their original
    // contents cannot be recovered, and must not be rehashed or treated as text.
    if (!original.isBinary() && !original.isHashed()) {
        if (original.isPostfixEncoded()) {
            // This postfix is an opaque leaf's raw payload, not encoded text.
            result._data = translate(original._data);
        }
        else {
            // Tag operation lengths can span the data/postfix boundary.
            auto data = translate(original._data);
            auto whole = translate(original._data + original._postfix);
            result._data = whole.left(data.size());
            result._postfix = whole.mid(data.size());
        }
        int offset = original.isPostfixEncoded() ? 1 : 0;
        if (original.isIndexed() || original.isPrefixID() || original.isPrefixIDIndex()) {
            if (result._sids.size() <= offset) {
                throw Base::RuntimeError("Missing encoded string prefix");
            }
            if (!original.isIndexed()) {
                result._data = result._sids[offset].deref().toString().c_str();
                if (original.isPrefixIDIndex()) {
                    result._data += ':';
                }
            }
        }
    }

    auto existing = _target->_hashes->left.find(&result);
    if (existing != _target->_hashes->left.end()) {
        imported = existing->first;
        if (original.isPersistent()) {
            imported.setPersistent(true);
        }
    }
    else {
        // Related identities have been inserted first, as required by the
        // persistent string table's backward-reference encoding.
        result._id = _target->lastID() + 1;
        imported = _target->insert(imported);
    }
    _imported.emplace(&original, std::make_pair(StringIDRef(source, 0), imported));
    return {imported, source.getIndex()};
}

namespace
{
QByteArray translateMappedReferences(
    const QByteArray& text,
    const QVector<StringIDRef>& references,
    const StringHasherRef& source,
    const std::function<StringIDRef(const StringIDRef&)>& translateID,
    const std::set<const StringID*>& pending,
    const std::function<void(const StringIDRef&)>& retain
)
{
    auto aggregateMembers = [](const QByteArray& bytes) {
        std::vector<QByteArray> members;
        if (bytes.size() < 3 || bytes.front() != '(' || bytes.back() != ')') {
            return members;
        }
        int depth = 1;
        int start = 1;
        for (int index = 1; index + 1 < bytes.size(); ++index) {
            if (bytes[index] == '(') {
                ++depth;
            }
            else if (bytes[index] == ')') {
                if (--depth < 1) {
                    return std::vector<QByteArray>();
                }
            }
            else if (bytes[index] == '|' && depth == 1) {
                members.push_back(bytes.mid(start, index - start));
                start = index + 1;
            }
        }
        if (depth != 1) {
            return std::vector<QByteArray>();
        }
        members.push_back(bytes.mid(start, bytes.size() - start - 1));
        return members;
    };
    std::map<long, StringIDRef> backed;
    std::set<const StringID*> visited;
    std::function<void(const StringIDRef&)> collect = [&](const StringIDRef& sid) {
        if (!sid || !visited.insert(&sid.deref()).second) {
            return;
        }
        if (!source || sid.isFromSameHasher(source)) {
            auto [it, inserted] = backed.emplace(sid.value(), sid);
            if (!inserted && !it->second.isFromSameHasher(sid.getHasher())) {
                throw Base::RuntimeError("Ambiguous encoded string identity");
            }
        }
        for (const auto& child : sid.relatedIDs()) {
            collect(child);
        }
    };
    for (const auto& sid : references) {
        collect(sid);
    }
    // Native combo-name leaves store tagged names separated by '|'. Their
    // retention dependencies are on the parent SID rather than the leaf.
    // Do not infer this for ordinary leaves such as "(#1)" or operation text.
    auto members = aggregateMembers(text);
    bool taggedAggregate = !members.empty()
        && std::all_of(members.begin(), members.end(), [](const auto& member) {
               return Data::MappedName::fromRawData(member)
                          .findTagInElementName(nullptr, nullptr, nullptr, nullptr, true, false)
                   >= 0;
           });
    if (references.empty() && taggedAggregate) {
        for (const auto* parent : pending) {
            if (!source || parent->isFromSameHasher(source)) {
                for (const auto& sid : parent->relatedIDs()) {
                    collect(sid);
                }
            }
        }
    }
    if (backed.empty() && !taggedAggregate) {
        return QByteArray(text.constData(), text.size());
    }

    auto translateToken = [&](const QByteArray& bytes, int position) {
        int end = position + 1;
        auto isHex = [](char ch) {
            return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F');
        };
        while (end < bytes.size() && isHex(bytes[end])) {
            ++end;
        }
        if (end == position + 1) {
            return bytes;
        }
        if (end + 1 < bytes.size() && bytes[end] == ':' && isHex(bytes[end + 1])) {
            ++end;
            while (end < bytes.size() && isHex(bytes[end])) {
                ++end;
            }
        }
        auto id = StringID::fromString(bytes.constData() + position, true, end - position);
        auto found = backed.find(id.id);
        StringIDRef original = found != backed.end() ? found->second : StringIDRef();
        if (!original && taggedAggregate && source) {
            original = source->getID(id.id);
        }
        if (!original) {
            return bytes;
        }
        auto imported = translateID(StringIDRef(original, id.index));
        if (retain) {
            retain(imported);
        }
        auto translated = imported.toString();
        return bytes.left(position) + QByteArray(translated.data(), translated.size())
            + bytes.mid(end);
    };

    std::function<QByteArray(const QByteArray&, bool)> translate;
    translate = [&](const QByteArray& bytes, bool operation) -> QByteArray {
        if (bytes.isEmpty()) {
            return bytes;
        }
        int nameLength = 0;
        int tag = Data::MappedName::fromRawData(bytes)
                      .findTagInElementName(nullptr, &nameLength, nullptr, nullptr, true, false);
        if (tag >= 0 && nameLength >= 0 && nameLength <= tag) {
            auto prefix = translate(bytes.left(nameLength), operation);
            auto op = translate(bytes.mid(nameLength, tag - nameLength), true);
            auto suffix = bytes.mid(tag);
            int colon = suffix.indexOf(':', Data::POSTFIX_TAG_SIZE);
            if (colon >= 0) {
                int end = suffix.indexOf(',', colon + 1);
                bool decimal = suffix.startsWith(Data::POSTFIX_DECIMAL_TAG);
                if (decimal) {
                    end = suffix.indexOf(':', colon + 1);
                }
                if (end >= 0) {
                    auto length = QByteArray::number(
                        static_cast<qlonglong>(decimal ? prefix.size() : op.size()),
                        decimal ? 10 : 16
                    );
                    suffix.replace(colon + 1, end - colon - 1, length);
                }
            }
            return prefix + op + suffix;
        }
        if (!operation) {
            auto parts = aggregateMembers(bytes);
            if (!parts.empty()) {
                QByteArray result("(");
                for (const auto& part : parts) {
                    if (result.size() != 1) {
                        result += '|';
                    }
                    result += translate(part, false);
                }
                return result + ')';
            }
            int separator = bytes.indexOf(';');
            auto prefix = separator < 0 ? bytes : bytes.left(separator);
            if (prefix.startsWith('#')) {
                prefix = translateToken(prefix, 0);
            }
            return separator < 0 ? prefix : prefix + translate(bytes.mid(separator), true);
        }

        // A tag's operation span contains both reserved naming codes and
        // arbitrary caller-supplied operation labels. Only reserved codes
        // encode references; a label like "Seed#1" or "(#1)" is literal.
        QByteArray result;
        int start = 0;
        while (start < bytes.size()) {
            int end = bytes.indexOf(';', start + 1);
            if (end < 0) {
                end = bytes.size();
            }
            auto chunk = bytes.mid(start, end - start);
            int marker = 0;
            if (chunk.startsWith(";:MG")) {
                marker = 4;
            }
            else if (
                chunk.startsWith(Data::MAPPED_CHILD_ELEMENTS_PREFIX)
                || chunk.startsWith(Data::POSTFIX_MOD) || chunk.startsWith(Data::POSTFIX_GEN)
                || chunk.startsWith(Data::POSTFIX_LOWER) || chunk.startsWith(Data::POSTFIX_UPPER)
            ) {
                marker = 3;
            }
            if (marker) {
                while (marker < chunk.size() && chunk[marker] >= '0' && chunk[marker] <= '9') {
                    ++marker;
                }
                if (marker < chunk.size() && chunk[marker] == '#') {
                    chunk = translateToken(chunk, marker);
                }
            }
            result += chunk;
            start = end;
        }
        return result;
    };
    return translate(text, false);
}
}  // namespace

QByteArray StringHasher::Importer::importReferences(
    const QByteArray& text,
    const QVector<StringIDRef>& references,
    const StringHasherRef& source
)
{
    return translateMappedReferences(
        text,
        references,
        source,
        [this](const auto& sid) { return importID(sid); },
        _pending
    );
}

StringIDRef StringHasher::getID(long id, int index) const
{
    if (id <= 0) {
        return {};
    }
    auto it = _hashes->right.find(id);
    if (it == _hashes->right.end()) {
        return {};
    }
    StringIDRef res(it->second);
    res._index = index;
    return res;
}

void StringHasher::setPersistenceFileName(const char* filename) const
{
    if (!filename) {
        filename = "";
    }
    _filename = filename;
}

const std::string& StringHasher::getPersistenceFileName() const
{
    return _filename;
}

void StringHasher::Save(Base::Writer& writer) const
{

    std::size_t count = _hashes->SaveAll ? _hashes->size() : this->count();

    writer.Stream() << writer.ind() << "<StringHasher saveall=\"" << _hashes->SaveAll
                    << "\" threshold=\"" << _hashes->Threshold << "\"";

    if (count == 0U) {
        writer.Stream() << " count=\"0\"></StringHasher>\n";
        return;
    }

    writer.Stream() << " count=\"0\" new=\"1\"/>\n";

    writer.Stream() << writer.ind() << "<StringHasher2 ";
    if (!_filename.empty()) {
        writer.Stream() << " file=\"" << writer.addFile((_filename + ".txt").c_str(), this)
                        << "\"/>\n";
        return;
    }

    writer.Stream() << " count=\"" << count << "\">\n";
    saveStream(writer.beginCharStream() << '\n');
    writer.endCharStream() << '\n';
    writer.Stream() << writer.ind() << "</StringHasher2>\n";
}

void StringHasher::SaveDocFile(Base::Writer& writer) const
{
    std::size_t count = _hashes->SaveAll ? this->size() : this->count();
    writer.Stream() << "StringTableStart v1 " << count << '\n';
    saveStream(writer.Stream());
}

void StringHasher::saveStream(std::ostream& stream) const
{
    Base::TextOutputStream textStreamWrapper(stream);
    boost::io::ios_flags_saver ifs(stream);
    stream << std::hex;

    long anchor = 0;
    const StringID* last = nullptr;
    long lastID = 0;
    bool relative = false;

    for (auto& hasher : _hashes->right) {
        auto& d = *hasher.second;
        long id = d._id;
        if (!_hashes->SaveAll && !d.isMarked() && !d.isPersistent()) {
            continue;
        }

        // We use relative coding to save space. But in order to have some
        // minimum protection against corruption, write an absolute value every
        // once a while.
        relative = (id - anchor) < 1000;
        if (relative) {
            stream << '-' << id - lastID;
        }
        else {
            anchor = id;
            stream << id;
        }
        lastID = id;

        int offset = d.isPostfixEncoded() ? 1 : 0;

        StringID::IndexID prefixID {};
        prefixID.id = 0;
        prefixID.index = 0;
        if (d.isPrefixID()) {
            assert(d._sids.size() > offset);
            prefixID.id = d._sids[offset].value();
        }
        else if (d.isPrefixIDIndex()) {
            prefixID = StringID::fromString(d._data);
            assert(d._sids.size() > offset && d._sids[offset].value() == prefixID.id);
        }

        auto flags = d._flags;
        flags.setFlag(StringID::Flag::Marked, false);
        stream << '.' << flags.toUnderlyingType();

        int position = 0;
        if (!relative) {
            for (; position < d._sids.size(); ++position) {
                stream << '.' << d._sids[position].value();
            }
        }
        else {
            if (last) {
                for (; position < d._sids.size() && position < last->_sids.size(); ++position) {
                    long m = last->_sids[position].value();
                    long n = d._sids[position].value();
                    if (n < m) {
                        stream << ".-" << m - n;
                    }
                    else {
                        stream << '.' << n - m;
                    }
                }
            }
            for (; position < d._sids.size(); ++position) {
                stream << '.' << id - d._sids[position].value();
            }
        }

        last = &d;

        // Having postfix means it is a geometry element name, which
        // guarantees to be a single line without space. So it is safe to
        // store in raw stream.
        if (d.isPostfixed()) {
            if (!d.isPrefixIDIndex() && !d.isIndexed() && !d.isPrefixID()) {
                stream << ' ' << d._data.constData();
            }

            if (!d.isPostfixEncoded()) {
                stream << ' ' << d._postfix.constData();
            }
            stream << '\n';
        }
        else {
            // Reaching here means the string may contain space and newlines
            // We rely on OutputStream (i.e. textStreamWrapper) to save the string.
            stream << ' ';
            if (d.isHashed() || d.isBinary()) {
                // restoreStreamNew decodes opaque payloads from base64. Never
                // send raw binary through a null-terminated text writer.
                textStreamWrapper << d._data.toBase64().constData();
            }
            else {
                textStreamWrapper << d._data.constData();
            }
        }
    }
}

void StringHasher::RestoreDocFile(Base::Reader& reader)
{
    std::string marker;
    std::string ver;
    reader >> marker;
    std::size_t count = 0;
    _hashes->clear();
    if (marker == "StringTableStart") {
        reader >> ver >> count;
        if (ver != "v1") {
            FC_WARN("Unknown string table format");
        }
        restoreStreamNew(reader, count);
        return;
    }
    reader >> count;
    restoreStream(reader, count);
}

void StringHasher::restoreStreamNew(std::istream& stream, std::size_t count)
{
    Base::TextInputStream asciiStream(stream);
    _hashes->clear();
    std::string content;
    boost::io::ios_flags_saver ifs(stream);
    stream >> std::hex;
    std::vector<std::string> tokens;
    long lastid = 0;
    const StringID* last = nullptr;

    std::string tmp;

    for (uint32_t i = 0; i < count; ++i) {
        if (!(stream >> tmp)) {
            FC_THROWM(Base::RuntimeError, "Invalid string table");
        }

        tokens.clear();
        boost::split(tokens, tmp, boost::is_any_of("."));
        if (tokens.size() < 2) {
            FC_THROWM(Base::RuntimeError, "Invalid string table");
        }

        long id = 0;
        bool relative = false;
        if (tokens[0][0] == '-') {
            relative = true;
            id = lastid + strtol(tokens[0].c_str() + 1, nullptr, 16);
        }
        else {
            id = strtol(tokens[0].c_str(), nullptr, 16);
        }

        lastid = id;

        unsigned long flag = strtol(tokens[1].c_str(), nullptr, 16);
        StringIDRef sid(new StringID(id, QByteArray(), static_cast<StringID::Flag>(flag)));

        StringID& d = *sid._sid;
        d._sids.reserve(tokens.size() - 2);

        int j = 2;
        if (relative && last) {
            for (; j < (int)tokens.size() && j - 2 < last->_sids.size(); ++j) {
                long m = last->_sids[j - 2].value();
                long n;
                if (tokens[j][0] == '-') {
                    n = -strtol(&tokens[j][1], nullptr, 16);
                }
                else {
                    n = strtol(&tokens[j][0], nullptr, 16);
                }
                StringIDRef sid = getID(m + n);
                if (!sid) {
                    FC_THROWM(Base::RuntimeError, "Invalid string id reference");
                }
                d._sids.push_back(sid);
            }
        }
        for (; j < (int)tokens.size(); ++j) {
            long n = strtol(tokens[j].data(), nullptr, 16);
            StringIDRef sid = getID(relative ? id - n : n);
            if (!sid) {
                FC_THROWM(Base::RuntimeError, "Invalid string id reference");
            }
            d._sids.push_back(sid);
        }

        if (!d.isPostfixed()) {
            asciiStream >> content;
            if (d.isHashed() || d.isBinary()) {
                d._data = QByteArray::fromBase64(content.c_str());
            }
            else {
                d._data = content.c_str();
            }
        }
        else {
            int offset = 0;
            if (d.isPostfixEncoded()) {
                offset = 1;
                if (d._sids.empty()) {
                    FC_THROWM(Base::RuntimeError, "Missing string postfix");
                }
                d._postfix = d._sids[0]._sid->_data;
            }
            if (d.isIndexed()) {
                if (d._sids.size() <= offset) {
                    FC_THROWM(Base::RuntimeError, "Missing string prefix");
                }
                d._data = d._sids[offset]._sid->_data;
            }
            else if (d.isPrefixID() || d.isPrefixIDIndex()) {
                if (d._sids.size() <= offset) {
                    FC_THROWM(Base::RuntimeError, "Missing string prefix id");
                }
                d._data = d._sids[offset]._sid->toString(0).c_str();
                if (d.isPrefixIDIndex()) {
                    d._data += ":";
                }
            }
            else {
                stream >> content;
                d._data = content.c_str();
            }
            if (!d.isPostfixEncoded()) {
                stream >> content;
                d._postfix = content.c_str();
            }
        }

        last = insert(sid);
    }
}

StringID* StringHasher::insert(const StringIDRef& sid)
{
    assert(sid && sid._sid->_hasher == nullptr);
    auto& hasher = *sid._sid;
    hasher._hasher = this;
    hasher.ref();
    auto res = _hashes->right.insert(_hashes->right.end(),
                                     HashMap::right_map::value_type(sid.value(), &hasher));
    if (res->second != &hasher) {
        hasher._hasher = nullptr;
        hasher.unref();
    }
    return res->second;
}

void StringHasher::restoreStream(std::istream& stream, std::size_t count)
{
    _hashes->clear();
    std::string content;
    for (uint32_t i = 0; i < count; ++i) {
        int32_t id = 0;
        uint8_t type = 0;
        stream >> id >> type >> content;
        StringIDRef sid = new StringID(id, QByteArray(), static_cast<StringID::Flag>(type));
        if (sid.isHashed() || sid.isBinary()) {
            sid._sid->_data = QByteArray::fromBase64(content.c_str());
        }
        else {
            sid._sid->_data = QByteArray(content.c_str());
        }
        insert(sid);
    }
}

void StringHasher::clear()
{
    for (auto& hasher : _hashes->right) {
        hasher.second->_hasher = nullptr;
        hasher.second->unref();
    }
    _hashes->clear();
}

size_t StringHasher::size() const
{
    return _hashes->size();
}

size_t StringHasher::count() const
{
    size_t count = 0;
    for (auto& hasher : _hashes->right) {
        if (hasher.second->isMarked() || hasher.second->isPersistent()) {
            ++count;
        }
    }
    return count;
}

void StringHasher::Restore(Base::XMLReader& reader)
{
    clear();
    reader.readElement("StringHasher");
    _hashes->SaveAll = reader.getAttribute<long>("saveall") != 0L;
    _hashes->Threshold = reader.getAttribute<int>("threshold");

    bool newTag = false;
    if (reader.hasAttribute("new") && reader.getAttribute<bool>("new")) {
        reader.readElement("StringHasher2");
        newTag = true;
    }

    if (reader.hasAttribute("file")) {
        const char* file = reader.getAttribute<const char*>("file");
        if (*file != '\0') {
            reader.addFile(file, this);
        }
        return;
    }

    std::size_t count = reader.getAttribute<unsigned long>("count");
    if (newTag) {
        try {
            restoreStreamNew(reader.beginCharStream(), count);
        }
        catch (const Base::Exception& e) {
            e.reportException();
            FC_ERR("Failed to restore string table: full-document recompute strongly recommended.");
        }
        reader.readEndElement("StringHasher2");
        return;
    }
    if ((count != 0U) && reader.FileVersion > 1) {
        restoreStream(reader.beginCharStream(), count);
    }
    else {
        for (std::size_t i = 0; i < count; ++i) {
            reader.readElement("Item");
            StringIDRef sid;
            long id = reader.getAttribute<long>("id");
            bool hashed = reader.hasAttribute("hash");
            if (hashed || reader.hasAttribute("data")) {
                const char* value =
                    hashed ? reader.getAttribute<const char*>("hash") : reader.getAttribute<const char*>("data");
                sid = new StringID(id, QByteArray::fromBase64(value), StringID::Flag::Hashed);
            }
            else {
                sid = new StringID(id, QByteArray(reader.getAttribute<const char*>("text")));
            }
            insert(sid);
        }
    }
    reader.readEndElement("StringHasher");
}

unsigned int StringHasher::getMemSize() const
{
    return (_hashes->SaveAll ? size() : count()) * 10;
}

PyObject* StringHasher::getPyObject()
{
    return new StringHasherPy(this);
}

std::map<long, StringIDRef> StringHasher::getIDMap() const
{
    std::map<long, StringIDRef> ret;
    for (auto& hasher : _hashes->right) {
        ret.emplace_hint(ret.end(), hasher.first, StringIDRef(hasher.second));
    }
    return ret;
}

void StringHasher::clearMarks() const
{
    for (auto& hasher : _hashes->right) {
        hasher.second->_flags.setFlag(StringID::Flag::Marked, false);
    }
}
